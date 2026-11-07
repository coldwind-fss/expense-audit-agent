"""A single explicit LangGraph runtime, with typed LangChain model actions and tools."""

import asyncio
from datetime import date
from typing import Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import update

from .agent_service import step_record
from .config import settings
from .db import SessionLocal
from .errors import AppError
from .model_gateway import FixtureModelGateway, ProviderModelGateway
from .models import AgentRun, Job, Material
from .rules import evaluate
from .schemas import MoneyInput
from .task_handlers import HANDLERS

GRAPH_VERSION = "reimbursement.v2.1"


class Transaction(BaseModel):
    id: str = Field(min_length=1)
    amount: MoneyInput


class Facts(BaseModel):
    document_role: Literal[
        "payment", "tax_invoice", "title_exempt_transport_receipt", "supporting_document", "unknown"
    ]
    amount: MoneyInput = None
    payment_status: Literal["paid", "unpaid", "unknown"] = "unknown"
    business_date: str | None = None
    date_type: Literal["transaction", "invoice_issue", "ride", "flight", "stay", "unknown"] = "unknown"
    refund_amount: MoneyInput = None
    refund_linked: bool = False
    refund_status: Literal["none", "pending", "completed", "unknown"] = "unknown"
    transaction_id: str = ""
    transactions: list[Transaction] = Field(default_factory=list)
    invoice_number: str = ""
    buyer_name: str = ""
    buyer_tax_number: str = ""
    seller_name: str = ""
    seller_tax_number: str = ""
    invoice_date: str = ""
    invoice_type: str = ""
    item_name: str = ""
    net_amount: MoneyInput = None
    tax_amount: MoneyInput = None
    expense_type: str = ""
    merchant: str = ""
    observations: list[dict] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)

    @field_validator("business_date", "invoice_date")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class Action(BaseModel):
    action: Literal["tool", "finish", "ask", "fail"]
    tool_name: str = ""
    arguments: dict = Field(default_factory=dict)
    facts: Facts | None = None
    question: dict = Field(default_factory=dict)
    reason: str = ""


class State(TypedDict, total=False):
    snapshot: dict
    task_kind: str
    mode: str
    action: dict
    observations: dict
    rounds: int
    no_progress: int
    review: dict
    response: dict
    output: dict
    stop_reason: str


def make_tools(snapshot: dict, task_kind: str):
    if task_kind == "material_extract":
        allowed = {snapshot["material"]["id"]}
    else:
        allowed = {m["id"] for m in snapshot["claim"]["materials"]}

    @tool
    def read_material_pages(material_id: str, page: int = 0) -> dict:
        """Read an authorized material page and return a source reference, not invented OCR."""
        if material_id not in allowed:
            raise AppError("FORBIDDEN", "工具不能访问当前任务以外的材料", 403)
        from .api_materials import file_path

        with SessionLocal() as db:
            material = db.get_one(Material, material_id)
            if not material or page < 0 or page > len(material.pages):
                raise AppError("RESOURCE_NOT_FOUND", "材料页不可读", 404)
            selected = list(range(1, len(material.pages) + 1)) if page == 0 else [page]
            exists = bool(selected) and all(
                file_path(material.pages[number - 1]).is_file() for number in selected
            )
            if not exists:
                raise AppError("MATERIAL_UNAVAILABLE", "材料原件页不可用，请补传", 422)
            return {
                "material_id": material_id,
                "page": page,
                "pages": [{"page": number} for number in selected],
                "available": exists,
                "source": "registered_fixture" if material.fixture_data else "uploaded_original",
                "observations": material.fixture_data.get("observations", [])
                if snapshot.get("model_profile", {}).get("mode", "fixture") == "fixture"
                and material.fixture_data
                else [],
            }

    @tool
    def read_cached_facts() -> dict:
        """Load the exact authorized material facts from this immutable task snapshot."""
        return {
            "facts": [
                {"id": m["id"], "version": m["fact_version"], "facts": m["facts"]}
                for m in snapshot.get("claim", {}).get("materials", [])
            ]
        }

    @tool
    def calculate_supported_amounts() -> dict:
        """Calculate suggestions using exact decimal arithmetic and the assigned evidence."""
        from .agent_service import suggestions

        return {"suggestions": suggestions(snapshot)}

    @tool
    def run_rule_checks() -> dict:
        """Execute the required business checks; a model cannot change their pass/fail result."""
        return evaluate(snapshot)

    all_tools = {
        t.name: t
        for t in [read_material_pages, read_cached_facts, calculate_supported_amounts, run_rule_checks]
    }
    names = HANDLERS[task_kind].tools
    return {name: all_tools[name] for name in names}


def fixture_action(state: State) -> dict:
    task = state["task_kind"]
    seen = state.get("observations", {})
    if task == "material_extract":
        material = state["snapshot"]["material"]
        if "read_material_pages" not in seen:
            return {
                "action": "tool",
                "tool_name": "read_material_pages",
                "arguments": {"material_id": material["id"]},
            }
        if not material.get("fixture_data"):
            return {"action": "fail", "reason": "此材料没有登记合成样本；当前未接真实模型，不能自动识别"}
        return {"action": "finish", "facts": material["fixture_data"]}
    if "read_cached_facts" not in seen:
        return {"action": "tool", "tool_name": "read_cached_facts"}
    tool_name = "calculate_supported_amounts" if task == "line_suggest" else "run_rule_checks"
    if tool_name not in seen:
        return {"action": "tool", "tool_name": tool_name}
    if task == "claim_review" and not state.get("response"):
        ambiguous = next(
            (
                m
                for m in state["snapshot"]["claim"]["materials"]
                if m["facts"].get("candidates")
                and m["facts"].get("document_role") in {"payment", "unknown"}
                and m.get("manual_amount") is None
            ),
            None,
        )
        if ambiguous:
            return {
                "action": "ask",
                "question": {
                    "kind": "manual_amount",
                    "material_id": ambiguous["id"],
                    "text": f"{ambiguous['name']}有多个金额，请核对实际付款并确认金额。",
                    "candidates": ambiguous["facts"].get("candidates", []),
                },
            }
    return {"action": "finish"}


async def execute(run_id: str, job_id: str, lease_token: str, resume: dict | None = None) -> dict:
    with SessionLocal() as db:
        run = db.get_one(AgentRun, run_id)
        snapshot, task, mode, attempt = run.snapshot, run.task_kind, run.execution_mode, run.attempt_id
    tools = make_tools(snapshot, task)
    profile = HANDLERS[task]
    model_limit, tool_limit = profile.model_limit, profile.tool_limit

    def record(node: str, detail: dict, counter: str | None = None):
        with SessionLocal() as db:
            job = db.get_one(Job, job_id)
            run = db.get_one(AgentRun, run_id)
            if (
                not job
                or job.status != "running"
                or job.lease_token != lease_token
                or run.status in {"cancelled", "outdated", "completed"}
            ):
                raise AppError("RESULT_OUTDATED", "任务已取消或被新执行替代", 409)
            if counter:
                column = getattr(AgentRun, counter)
                limit = model_limit if counter == "model_calls" else tool_limit
                changed = db.scalar(
                    update(AgentRun)
                    .where(AgentRun.id == run_id, column < limit)
                    .values({counter: column + 1})
                    .returning(AgentRun.id)
                )
                if not changed:
                    raise AppError(
                        "MODEL_BUDGET_LIMIT", "本次处理已达到执行预算，未完成项不会被当作通过", 429
                    )
            step_record(db, run, node, detail)
            db.commit()

    async def model_step(state: State):
        if mode == "disabled":
            raise AppError(
                "PROVIDER_NOT_CONFIGURED", "当前未配置真实模型；可使用登记合成样本体验完整流程", 503
            )
        if mode == "provider":
            seen = state.get("observations", {})
            required = (
                ["read_material_pages"]
                if task == "material_extract"
                else (["read_cached_facts", "run_rule_checks"] if task == "claim_review" else [])
            )
            pending = next((name for name in required if name not in seen), None)
            if pending:
                arguments = (
                    {"material_id": snapshot["material"]["id"], "page": 0}
                    if pending == "read_material_pages"
                    else {}
                )
                return {
                    "action": {"action": "tool", "tool_name": pending, "arguments": arguments},
                    "rounds": state.get("rounds", 0) + 1,
                }
        # Suggestions with sufficient facts are deterministic and need no additional model call.
        action = fixture_action(state) if mode == "fixture" or task == "line_suggest" else {}
        if task != "line_suggest":
            record("model", {"prompt_version": f"{task}.v2.1" if mode == "provider" else f"{task}.v1", "mode": mode}, "model_calls")
            if mode == "provider":
                gateway = ProviderModelGateway(snapshot["model_profile"])
                context = {
                    "snapshot": snapshot,
                    "task_kind": task,
                    "observations": state.get("observations", {}),
                    "response": state.get("response", {}),
                    "allowed_tools": {
                        name: tool.args_schema.model_json_schema() for name, tool in tools.items()
                    },
                }
                try:
                    parsed = await gateway.invoke(profile.prompt, Action, {}, context)
                finally:
                    record(
                        "provider_usage", {"model_profile": snapshot["model_profile"], "usage": gateway.usage}
                    )
            else:
                parsed = await FixtureModelGateway().invoke(profile.prompt, Action, action)
            action = parsed.model_dump(mode="json", exclude_none=True)
        else:
            action = Action.model_validate(action).model_dump(mode="json", exclude_none=True)
        return {"action": action, "rounds": state.get("rounds", 0) + 1}

    async def tool_step(state: State):
        action = state["action"]
        name = action["tool_name"]
        if name not in tools:
            raise AppError("FORBIDDEN", "工具不在本任务白名单中", 403)
        record("tool", {"name": name, "arguments": action.get("arguments", {})}, "tool_calls")
        result = await asyncio.to_thread(tools[name].invoke, action.get("arguments", {}))
        observations = {**state.get("observations", {}), name: result}
        repeats = state.get("no_progress", 0) + 1 if state.get("observations", {}).get(name) == result else 0
        return {
            "observations": observations,
            "no_progress": repeats,
            "review": result if name == "run_rule_checks" else state.get("review", {}),
        }

    def route(state: State):
        if state.get("rounds", 0) >= 12 or state.get("no_progress", 0) >= 2:
            return "stop"
        return {"tool": "tools", "finish": "finish", "ask": "human", "fail": "stop"}[
            state["action"]["action"]
        ]

    def human(state: State):
        question = {**state["action"]["question"], "question_id": f"{run_id}:confirmation"}
        if question.get("kind") == "manual_amount":
            material = next(
                (
                    m
                    for m in snapshot.get("claim", {}).get("materials", [])
                    if m["id"] == question.get("material_id")
                ),
                None,
            )
            if (
                not material
                or material["kind"] != "payment"
                or material["facts"].get("document_role") not in {"payment", "unknown"}
            ):
                raise AppError("INVALID_HUMAN_QUESTION", "模型请求的人工确认不在允许的材料/字段范围", 422)
        response = interrupt(question)
        return {"response": response}

    def finish(state: State):
        if task == "material_extract":
            seen = state.get("observations", {}).get("read_material_pages", {})
            if set(p["page"] for p in seen.get("pages", [])) != set(
                range(1, len(snapshot["material"]["pages"]) + 1)
            ):
                raise AppError("INCOMPLETE_EVIDENCE", "材料页尚未全部读取，不能发布识别结果", 422)
            if not state["action"].get("facts"):
                raise AppError("MODEL_STRUCTURE_INVALID", "模型没有给出材料事实", 422)
            return {"output": {"facts": state["action"]["facts"]}, "stop_reason": "task_complete"}
        if task == "claim_review" and not state.get("review"):
            raise AppError("INCOMPLETE_REVIEW", "必要业务检查尚未执行，不能生成通过报告", 422)
        return {"output": {"review": state.get("review", {})}, "stop_reason": "task_complete"}

    def stop(state: State):
        return {
            "output": {},
            "stop_reason": state["action"].get("reason") or "执行没有新进展，已停止自动尝试",
        }

    builder = StateGraph(State)
    builder.add_node("model", model_step)
    builder.add_node("tools", tool_step)
    builder.add_node("human", human)
    builder.add_node("finish", finish)
    builder.add_node("stop", stop)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route)
    builder.add_edge("tools", "model")
    builder.add_edge("human", "model")
    builder.add_edge("finish", END)
    builder.add_edge("stop", END)
    config: RunnableConfig = {"configurable": {"thread_id": f"{run_id}:{attempt}"}, "recursion_limit": 40}
    async with AsyncPostgresSaver.from_conn_string(settings().checkpoint_url) as saver:
        graph = builder.compile(checkpointer=saver)
        graph_input: State | Command = (
            Command(resume=resume)
            if resume is not None
            else {
                "snapshot": snapshot,
                "task_kind": task,
                "mode": mode,
                "observations": {},
                "rounds": 0,
            }
        )
        result = await asyncio.wait_for(graph.ainvoke(graph_input, config), timeout=profile.timeout_seconds)
    if result.get("__interrupt__"):
        return {"waiting": result["__interrupt__"][0].value, "partial_review": result.get("review", {})}
    if not result.get("output"):
        raise AppError("PROCESSING_INCOMPLETE", result.get("stop_reason", "处理未完成"), 422)
    return result["output"]
