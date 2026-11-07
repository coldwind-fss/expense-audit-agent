# ruff: noqa: E402
"""Explicit live evaluation. No real model call is made by pytest/CI or without --live."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true")
parser.add_argument("--sample-limit", type=int, default=10)
parser.add_argument("--scenario-limit", type=int, default=8)
parser.add_argument("--max-calls", type=int, default=60)
parser.add_argument("--output", default="../data/v2/model-evaluation.json")
args = parser.parse_args()
if not args.live:
    parser.error("Live evaluation requires the explicit --live flag and a server-side API key")
os.environ["MODEL_MODE"] = "provider"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://reimbursement:development@127.0.0.1:15432/reimbursement_v2_eval"
)
os.environ.setdefault(
    "CHECKPOINT_URL",
    "postgresql://reimbursement:development@127.0.0.1:15432/reimbursement_v2_eval?options=-csearch_path%3Dagent_runtime",
)
os.environ.setdefault("FILE_ROOT", "../data/v2/eval-files")
if not os.environ["DATABASE_URL"].endswith("/reimbursement_v2_eval"):
    raise RuntimeError("Use the dedicated reimbursement_v2_eval database for live evaluation")

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reimbursement.config import settings
from reimbursement.db import SessionLocal
from reimbursement.fixtures import documents
from reimbursement.main import app
from reimbursement.model_gateway import model_profile
from reimbursement.models import AgentRun, AgentStep
from reimbursement.rules import POLICY_VERSION, normalize_facts
from reimbursement.worker import tick

logging.getLogger("reimbursement").setLevel(logging.ERROR)
if not settings().model_api_key.get_secret_value():
    raise RuntimeError("MODEL_API_KEY is not configured")
started = perf_counter()
report = {
    "mode": "provider",
    "model_profile": model_profile(),
    "fixture_version": "synthetic.v2",
    "policy_version": POLICY_VERSION,
    "samples": [],
    "workflows": [],
    "cost": None,
    "cost_note": "记录真实token用量；服务未返回账单金额，不推算费用",
}

with TestClient(app) as client:
    session = client.post("/api/v1/experience/sessions").json()
    workspace_id = session["workspace_id"]
    report["workspace_id"] = workspace_id
    client.headers["X-CSRF-Token"] = session["csrf_token"]

    def request(path, data=None, method="POST"):
        response = client.request(
            method, "/api/v1" + path, json=data, headers={"Idempotency-Key": str(uuid4())}
        )
        if not response.is_success:
            error = response.json().get("error", {})
            raise RuntimeError(f"{path}: {error.get('code')}: {error.get('message')}")
        return response.json()

    def get(path):
        return request(path, method="GET")

    def calls():
        with SessionLocal() as db:
            return db.scalar(
                select(func.coalesce(func.sum(AgentRun.model_calls), 0)).where(
                    AgentRun.workspace_id == workspace_id
                )
            )

    def drain():
        async def execute():
            for _ in range(80):
                if calls() >= args.max_calls:
                    raise RuntimeError("Live evaluation call budget reached")
                if not await tick(["prepare", "agent"]):
                    return
            raise RuntimeError("Queue did not settle")

        asyncio.run(execute())

    def upload(claim, key, line_id=None):
        sample = documents()[key]
        response = client.post(
            f"/api/v1/claims/{claim['id']}/materials",
            data={"kind": sample["kind"], **({"target_line_id": line_id} if line_id else {})},
            files={"file": (str(uuid4()) + ".png", sample["content"], "image/png")},
        )
        if response.status_code != 201:
            raise RuntimeError("Evaluation upload failed")
        return response.json()

    def finish_report():
        with SessionLocal() as db:
            steps = db.scalars(
                select(AgentStep).where(
                    AgentStep.workspace_id == workspace_id, AgentStep.node == "provider_usage"
                )
            ).all()
            report["usage"] = {
                name: sum(s.detail.get("usage", {}).get(name, 0) for s in steps)
                for name in ["input_tokens", "output_tokens", "total_tokens"]
            }
        report["false_passes"] = sum(
            not row["expected_can_submit"] and row["actual_can_submit"] is True for row in report["workflows"]
        )
        report["false_blocks"] = sum(
            row["expected_can_submit"] and row["actual_can_submit"] is not True for row in report["workflows"]
        )
        report["processing_failures"] = sum(
            row["status"] == "failed" for row in report["samples"] + report["workflows"]
        )
        report["human_confirmation_cases"] = sum(
            row["status"] == "waiting_input" for row in report["workflows"]
        )
        report["model_calls"] = calls()
        report["elapsed_seconds"] = round(perf_counter() - started, 2)
        report["scope"] = "仅本合成标签集，不代表真实公司票据准确率或实际财务验收"
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        for key, sample in list(documents().items())[: args.sample_limit]:
            claim = request("/claims", {"title": "真实模型材料评估"})
            material = upload(claim, key)
            drain()
            actual = get("/materials/" + material["id"])
            expected = normalize_facts(sample["facts"], material["id"])
            fields = ["document_role", "countable_amount", "business_date"]
            if sample["kind"] == "payment":
                fields += ["payment_status"]
            if sample["kind"] == "invoice":
                fields += ["invoice_number", "buyer_name"]
            differences = [
                {"field": name, "expected": expected.get(name), "actual": actual["facts"].get(name)}
                for name in fields
                if expected.get(name) != actual["facts"].get(name)
            ]
            report["samples"].append(
                {
                    "key": key,
                    "material_id": material["id"],
                    "status": actual["status"],
                    "differences": differences,
                    "actual_facts": actual["facts"],
                    "error": actual["error"],
                }
            )
            finish_report()
            print(
                json.dumps(
                    {
                        "sample": key,
                        "status": actual["status"],
                        "field_errors": len(differences),
                        "calls": calls(),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        cases = [
            "daily",
            "no_invoice",
            "travel",
            "project",
            "supply_chain",
            "wrong_title",
            "unpaid",
            "ambiguous",
        ]
        for case in cases[: args.scenario_limit]:
            workflow = (
                "daily"
                if case in {"wrong_title", "unpaid"}
                else "no_invoice"
                if case == "ambiguous"
                else case
            )
            if workflow == "supply_chain":
                request("/experience/persona", {"persona": "admin"})
            claim = request("/claims", {"title": "真实模型审核评估", "workflow_key": workflow})
            approvals = get("/related-approvals")["items"]
            line = {
                "expected_revision": claim["revision"],
                "reason": "出差交通费" if workflow == "travel" else "日常办公支出",
                "project": "日常运营",
                "invoice_type": "无" if workflow == "no_invoice" else "电子普票",
            }
            if workflow == "travel":
                line.update(
                    expense_type="差旅",
                    related_id=next(a["id"] for a in approvals if a["approval_type"] == "travel"),
                )
            claim = request(f"/claims/{claim['id']}/lines", line)
            keys = (
                ["payment_refund", "rail_ticket"]
                if workflow == "travel"
                else (
                    ["invoice_meal"]
                    if workflow == "supply_chain"
                    else ["payment_meal"]
                    if workflow == "no_invoice"
                    else ["payment_meal", "invoice_meal"]
                )
            )
            if case == "wrong_title":
                keys = ["payment_meal", "invoice_wrong_company"]
            if case == "unpaid":
                keys = ["order_unpaid", "invoice_meal"]
            if case == "ambiguous":
                keys = ["transfer_ambiguous"]
            for key in keys:
                upload(claim, key, claim["lines"][0]["id"])
            drain()
            claim = get("/claims/" + claim["id"])
            account = request(
                "/recipient-accounts", {"label": "模型评估合成账户", "value": "SYNTHETIC-EVAL-0001"}
            )
            claim = request(
                "/claims/" + claim["id"],
                {
                    "expected_revision": claim["revision"],
                    "account_id": account["id"],
                    "total_amount": "141.00" if workflow == "travel" else "88.00",
                },
                "PATCH",
            )
            claim = request(
                f"/claims/{claim['id']}/lines/{claim['lines'][0]['id']}",
                {
                    "expected_revision": claim["revision"],
                    "business_date": documents()[keys[0]]["facts"]["business_date"],
                    "amount": "141.00" if workflow == "travel" else "88.00",
                },
                "PATCH",
            )
            task = request(f"/claims/{claim['id']}/suggestions", {"expected_revision": claim["revision"]})
            drain()
            suggestion = get("/agent-runs/" + task["run_id"])
            task = request(f"/claims/{claim['id']}/reviews", {"expected_revision": claim["revision"]})
            drain()
            run = get("/agent-runs/" + task["run_id"])
            result = (
                get("/review-reports/" + run["output"]["report_id"])
                if run["output"].get("report_id")
                else None
            )
            report["workflows"].append(
                {
                    "workflow": case,
                    "status": run["status"],
                    "suggestion_status": suggestion["status"],
                    "expected_can_submit": case not in {"wrong_title", "unpaid", "ambiguous"},
                    "actual_can_submit": result["can_submit"] if result else False,
                    "report": result,
                    "error": run["error"],
                }
            )
            finish_report()
            print(
                json.dumps(
                    {
                        "workflow": case,
                        "status": run["status"],
                        "can_submit": result["can_submit"] if result else None,
                        "calls": calls(),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    except Exception as error:
        report["stopped"] = str(error)
        raise
    finally:
        finish_report()
        print(
            json.dumps(
                {"report_saved": str(Path(args.output).resolve()), "calls": report["model_calls"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
