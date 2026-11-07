from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_service import accepted, start_run
from .db import get_db, now
from .errors import AppError
from .models import (
    AgentRun,
    AgentStep,
    ClaimLine,
    HumanDecision,
    Job,
    Material,
    ReviewReport,
    SuggestionBatch,
)
from .rules import sync_line_amounts
from .schemas import MoneyInput, RevisionInput, TaskAccepted
from .security import Context, current_context
from .services import audit, bump_claim, check_revision, claim_view, command, load_claim, scoped

router = APIRouter(prefix="/api/v1")


def run_view(run):
    return {
        **accepted(run),
        "id": run.id,
        "claim_id": run.claim_id,
        "material_id": run.material_id,
        "output": run.output,
        "question": run.question,
        "error": run.error,
        "stop_reason": run.stop_reason,
        "model_calls": run.model_calls,
        "tool_calls": run.tool_calls,
        "created_at": run.created_at.isoformat(),
    }


@router.post("/materials/{material_id}/extract", response_model=TaskAccepted, status_code=202)
def extract(
    material_id: str,
    body: RevisionInput,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    material = scoped(db, Material, material_id, ctx.workspace_id)
    claim = load_claim(db, ctx, material.claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    if material.status == "deleted" or not material.pages:
        raise AppError("INVALID_STATE", "该材料没有可识别的图片页", 409)
    run = start_run(db, ctx, claim, "material_extract", material)
    db.commit()
    return accepted(run)


def begin(db, ctx, claim_id, body, task):
    claim = load_claim(db, ctx, claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    run = start_run(db, ctx, claim, task)
    db.commit()
    return accepted(run)


@router.post("/claims/{claim_id}/suggestions", response_model=TaskAccepted, status_code=202)
def suggest(
    claim_id: str, body: RevisionInput, ctx: Context = Depends(current_context), db: Session = Depends(get_db)
):
    return begin(db, ctx, claim_id, body, "line_suggest")


@router.post("/claims/{claim_id}/reviews", response_model=TaskAccepted, status_code=202)
def review(
    claim_id: str, body: RevisionInput, ctx: Context = Depends(current_context), db: Session = Depends(get_db)
):
    return begin(db, ctx, claim_id, body, "claim_review")


@router.get("/claims/{claim_id}/runs")
def runs(claim_id: str, ctx: Context = Depends(current_context), db: Session = Depends(get_db)):
    load_claim(db, ctx, claim_id)
    rows = db.scalars(
        select(AgentRun).where(AgentRun.claim_id == claim_id).order_by(AgentRun.created_at.desc()).limit(100)
    )
    return {"items": [run_view(r) for r in rows]}


@router.get("/agent-runs/{run_id}")
def get_run(run_id: str, ctx: Context = Depends(current_context), db: Session = Depends(get_db)):
    run = scoped(db, AgentRun, run_id, ctx.workspace_id)
    load_claim(db, ctx, run.claim_id)
    steps = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.created_at))
    return {
        **run_view(run),
        "steps": [{"node": s.node, "detail": s.detail, "at": s.created_at.isoformat()} for s in steps],
    }


@router.post("/agent-runs/{run_id}/cancel")
def cancel(run_id: str, ctx: Context = Depends(current_context), db: Session = Depends(get_db)):
    run = scoped(db, AgentRun, run_id, ctx.workspace_id)
    load_claim(db, ctx, run.claim_id, edit=True, lock=True)
    db.refresh(run)
    if run.status not in {"queued", "running", "waiting_input"}:
        raise AppError("INVALID_STATE", "此任务已结束", 409)
    run.status, run.finished_at, run.stop_reason = "cancelled", now(), "user_cancelled"
    job = db.scalars(select(Job).where(Job.kind == "agent", Job.entity_id == run.id).with_for_update()).one()
    if job:
        job.status, job.lease_token = "cancelled", None
    audit(db, ctx, "agent.cancelled", run.claim_id, run_id=run.id)
    db.commit()
    return run_view(run)


class HumanResponse(RevisionInput):
    question_id: str
    manual_amount: MoneyInput = None
    explanation: str = Field(default="", max_length=500)


@router.post("/agent-runs/{run_id}/responses", status_code=202)
def respond(
    run_id: str,
    body: HumanResponse,
    request: Request,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    def execute():
        run = scoped(db, AgentRun, run_id, ctx.workspace_id)
        claim = load_claim(db, ctx, run.claim_id, edit=True, lock=True)
        db.refresh(run)
        check_revision(claim, body.expected_revision)
        if (
            run.status != "waiting_input"
            or run.input_revision != claim.revision
            or run.question.get("question_id") != body.question_id
        ):
            raise AppError("INVALID_STATE", "问题已失效，请查看最新任务", 409)
        if run.question.get("kind") == "manual_amount":
            material = scoped(db, Material, run.question["material_id"], ctx.workspace_id)
            if (
                body.manual_amount is None
                or material.kind != "payment"
                or material.facts.get("document_role") not in {"payment", "unknown"}
            ):
                raise AppError("VALIDATION_ERROR", "请确认当前付款凭证的实际金额", 422)
            if material.facts.get("payment_status") == "unpaid":
                raise AppError("INVALID_REQUEST", "未付款订单不能人工确认为付款", 422)
            material.manual_amount = body.manual_amount
            db.add(
                HumanDecision(
                    workspace_id=ctx.workspace_id,
                    claim_id=claim.id,
                    material_id=material.id,
                    actor_id=ctx.actor.id,
                    decision_type="manual_amount",
                    value=body.model_dump(),
                )
            )
            sync_line_amounts(db, claim)
            bump_claim(db, ctx, claim, "human.amount_confirmed")
            run.status, run.stop_reason = "outdated", "human_input_changed"
            job = db.scalars(
                select(Job).where(Job.kind == "agent", Job.entity_id == run.id).with_for_update()
            ).one()
            job.status = "done"
            return accepted(start_run(db, ctx, claim, run.task_kind))
        job = db.scalars(
            select(Job).where(Job.kind == "agent", Job.entity_id == run.id).with_for_update()
        ).one()
        job.payload = {**job.payload, "resume": {"explanation": body.explanation}}
        job.status, job.available_at = "queued", now()
        run.status = "queued"
        return accepted(run)

    return command(
        db, ctx, request.headers.get("idempotency-key"), f"run.response:{run_id}", body.model_dump(), execute
    )


@router.get("/suggestion-batches/{batch_id}")
def get_batch(batch_id: str, ctx: Context = Depends(current_context), db: Session = Depends(get_db)):
    batch = scoped(db, SuggestionBatch, batch_id, ctx.workspace_id)
    claim = load_claim(db, ctx, batch.claim_id)
    return {
        "id": batch.id,
        "claim_id": batch.claim_id,
        "input_revision": batch.input_revision,
        "items": batch.items,
        "status": batch.status,
        "outdated": batch.status == "proposed" and claim.revision != batch.input_revision,
    }


class ApplySuggestions(RevisionInput):
    selected_indices: list[int]
    replace_manual: bool = False


@router.post("/suggestion-batches/{batch_id}/apply")
def apply_batch(
    batch_id: str,
    body: ApplySuggestions,
    request: Request,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    return command(
        db,
        ctx,
        request.headers.get("idempotency-key"),
        f"apply_batch:{batch_id}",
        body.model_dump(),
        lambda: _apply_batch(batch_id, body, ctx, db),
    )


def _apply_batch(
    batch_id: str,
    body: ApplySuggestions,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    batch = scoped(db, SuggestionBatch, batch_id, ctx.workspace_id)
    claim = load_claim(db, ctx, batch.claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    if batch.status != "proposed" or batch.input_revision != claim.revision:
        raise AppError("RESULT_OUTDATED", "回填建议已失效，请重新生成", 409)
    applied = []
    for index in sorted(set(body.selected_indices)):
        if index < 0 or index >= len(batch.items):
            raise AppError("VALIDATION_ERROR", "建议序号不正确", 422)
        item = batch.items[index]
        if item["protected"] and not body.replace_manual:
            raise AppError("MANUAL_VALUE_PROTECTED", "建议将替换人工填写值，请明确确认", 409)
        line = scoped(db, ClaimLine, item["line_id"], ctx.workspace_id)
        field, value = item["field"], item["value"]
        setattr(line, field, date.fromisoformat(value) if field == "business_date" else value)
        line.sources = {
            **line.sources,
            field: {"kind": "agent", "batch_id": batch.id, "evidence": item["evidence_refs"]},
        }
        applied.append(item)
    batch.status, batch.applied_values = "applied", applied
    bump_claim(db, ctx, claim, "suggestions.applied")
    return claim_view(db, claim)


@router.post("/suggestion-batches/{batch_id}/undo")
def undo_batch(
    batch_id: str,
    body: RevisionInput,
    request: Request,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    return command(
        db,
        ctx,
        request.headers.get("idempotency-key"),
        f"undo_batch:{batch_id}",
        body.model_dump(),
        lambda: _undo_batch(batch_id, body, ctx, db),
    )


def _undo_batch(
    batch_id: str, body: RevisionInput, ctx: Context = Depends(current_context), db: Session = Depends(get_db)
):
    batch = scoped(db, SuggestionBatch, batch_id, ctx.workspace_id)
    claim = load_claim(db, ctx, batch.claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    if batch.status != "applied":
        raise AppError("INVALID_STATE", "该批建议未应用或已撤回", 409)
    for item in batch.applied_values:
        line = scoped(db, ClaimLine, item["line_id"], ctx.workspace_id)
        field = item["field"]
        if line.sources.get(field, {}).get("batch_id") != batch.id or str(getattr(line, field) or "") != str(
            item["value"] or ""
        ):
            raise AppError("REVISION_CONFLICT", "回填值后来已被修改，不能覆盖该修改", 409)
        value = item["previous_value"]
        setattr(line, field, date.fromisoformat(value) if field == "business_date" and value else value)
        line.sources = {**line.sources, field: item["previous_source"]}
    batch.status = "undone"
    bump_claim(db, ctx, claim, "suggestions.undone")
    return claim_view(db, claim)


@router.get("/review-reports/{report_id}")
def report(report_id: str, ctx: Context = Depends(current_context), db: Session = Depends(get_db)):
    row = scoped(db, ReviewReport, report_id, ctx.workspace_id)
    claim = load_claim(db, ctx, row.claim_id)
    return {
        "id": row.id,
        "claim_id": row.claim_id,
        "input_revision": row.input_revision,
        "valid": row.valid and row.input_revision == claim.revision,
        "can_submit": row.can_submit,
        "checks": row.checks,
        "summary": row.summary,
        "execution_mode": row.execution_mode,
    }
