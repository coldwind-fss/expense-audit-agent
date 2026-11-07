import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_service import review_snapshot
from .api_claims import create_claim, patch_claim
from .catalogs import DIFFICULTIES as FEEDBACK_DIFFICULTIES
from .catalogs import PRIORITIES as FEEDBACK_PRIORITIES
from .db import get_db, now
from .errors import AppError
from .ledger import COLUMNS, rollback_entry, sync_event
from .models import (
    AdminAction,
    AuditEvent,
    ClaimRevision,
    Employee,
    FeedbackAnswer,
    FeedbackInvitation,
    Job,
    LedgerEntry,
    LedgerEvent,
    Submission,
    SupportCase,
)
from .rules import evaluate
from .schemas import ClaimCreate, ClaimPatch, Input, RevisionInput
from .security import Context, current_context, require_admin, token_hash
from .services import audit, claim_view, command, load_claim, scoped
from .submission_service import (
    StubApprovalGateway,
    business_time,
    confirm_created,
    create_submission,
    submission_view,
)

router = APIRouter(prefix="/api/v1")


def administrator(ctx: Context = Depends(current_context)):
    require_admin(ctx)
    return ctx


class Reason(Input):
    reason: str = Field(min_length=4, max_length=1000)


def admin_audit(db, ctx, action, reason, case_id=None, **detail):
    db.add(
        AdminAction(
            workspace_id=ctx.workspace_id,
            actor_id=ctx.actor.id,
            case_id=case_id,
            action=action,
            reason=reason,
            detail=detail,
        )
    )
    audit(db, ctx, f"admin.{action}", **detail)


def case_view(case):
    return {
        "id": case.id,
        "claim_id": case.claim_id,
        "subject_id": case.subject_id,
        "reason": case.reason,
        "status": case.status,
        "revision": case.revision,
    }


@router.get("/admin/cases")
def cases(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    return {
        "items": [
            case_view(x)
            for x in db.scalars(
                select(SupportCase)
                .where(SupportCase.workspace_id == ctx.workspace_id)
                .order_by(SupportCase.created_at.desc())
                .limit(100)
            )
        ]
    }


class ManualCase(Reason):
    subject_id: str
    workflow_key: Literal["daily", "no_invoice", "travel", "project", "supply_chain"] = "daily"
    title: str = Field(default="管理员协助报销", max_length=200)


@router.post("/admin/cases/manual", status_code=201)
def manual_case(
    body: ManualCase, request: Request, ctx: Context = Depends(administrator), db: Session = Depends(get_db)
):
    def execute():
        claim = create_claim(
            db,
            ctx,
            ClaimCreate(
                workflow_key=body.workflow_key,
                title=body.title,
                route_mode="admin_originator",
                subject_id=body.subject_id,
            ),
        )
        case = SupportCase(
            workspace_id=ctx.workspace_id, claim_id=claim.id, subject_id=claim.subject_id, reason=body.reason
        )
        db.add(case)
        db.flush()
        admin_audit(db, ctx, "case.created_only", body.reason, case.id, claim_id=claim.id)
        return case_view(case)

    return command(db, ctx, request.headers.get("idempotency-key"), "case.manual", body.model_dump(), execute)


class AttachCase(Reason):
    claim_id: str


@router.post("/admin/cases", status_code=201)
def attach_case(body: AttachCase, ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    claim = load_claim(db, ctx, body.claim_id)
    case = SupportCase(
        workspace_id=ctx.workspace_id, claim_id=claim.id, subject_id=claim.subject_id, reason=body.reason
    )
    db.add(case)
    db.flush()
    admin_audit(db, ctx, "case.attached", body.reason, case.id, claim_id=claim.id)
    db.commit()
    return case_view(case)


@router.get("/admin/cases/{case_id}")
def case_detail(case_id: str, ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    case = scoped(db, SupportCase, case_id, ctx.workspace_id)
    claim = load_claim(db, ctx, case.claim_id)
    revisions = db.scalars(
        select(ClaimRevision).where(ClaimRevision.claim_id == claim.id).order_by(ClaimRevision.revision)
    )
    actions = db.scalars(
        select(AdminAction).where(AdminAction.case_id == case.id).order_by(AdminAction.created_at)
    )
    return {
        **case_view(case),
        "claim": claim_view(db, claim),
        "revisions": [{"revision": r.revision, "at": r.created_at.isoformat()} for r in revisions],
        "actions": [{"action": a.action, "reason": a.reason, "detail": a.detail} for a in actions],
    }


class Repair(Reason):
    patch: ClaimPatch


@router.post("/admin/cases/{case_id}/repair")
def repair(
    case_id: str,
    body: Repair,
    request: Request,
    ctx: Context = Depends(administrator),
    db: Session = Depends(get_db),
):
    def execute():
        ctx.action_reason = body.reason
        case = scoped(db, SupportCase, case_id, ctx.workspace_id)
        claim = load_claim(db, ctx, case.claim_id, edit=True, lock=True)
        patch_claim(db, ctx, claim, body.patch)
        result = evaluate(review_snapshot(db, ctx, claim))
        if not result["can_submit"]:
            raise AppError(
                "SUBMISSION_BLOCKED",
                "修复后的申报仍未通过完整预校验，请在共享编辑器补齐明细/材料",
                422,
                result["checks"],
            )
        case.revision += 1
        admin_audit(db, ctx, "case.repaired", body.reason, case.id, claim_id=claim.id)
        return claim_view(db, claim)

    return command(
        db, ctx, request.headers.get("idempotency-key"), f"case.repair:{case_id}", body.model_dump(), execute
    )


class CaseSubmit(Reason, RevisionInput):
    review_id: str


@router.post("/admin/cases/{case_id}/submit", status_code=202)
def case_submit(
    case_id: str,
    body: CaseSubmit,
    request: Request,
    ctx: Context = Depends(administrator),
    db: Session = Depends(get_db),
):
    def execute():
        case = scoped(db, SupportCase, case_id, ctx.workspace_id)
        result = create_submission(
            db, ctx, case.claim_id, body.expected_revision, body.review_id, body.reason
        )
        case.status = "submitted"
        admin_audit(
            db,
            ctx,
            "case.submitted",
            body.reason,
            case.id,
            claim_id=case.claim_id,
            submission_id=result["id"],
        )
        return result

    return command(
        db, ctx, request.headers.get("idempotency-key"), f"case.submit:{case_id}", body.model_dump(), execute
    )


@router.get("/admin/jobs")
def jobs(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Job).where(Job.workspace_id == ctx.workspace_id).order_by(Job.created_at.desc()).limit(200)
    )
    return {
        "items": [
            {
                "id": x.id,
                "kind": x.kind,
                "entity_id": x.entity_id,
                "status": x.status,
                "attempts": x.attempts,
                "error": x.error,
                "available_at": x.available_at.isoformat(),
            }
            for x in rows
        ]
    }


@router.get("/admin/events")
def events(claim_id: str | None = None, ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    query = select(AuditEvent).where(AuditEvent.workspace_id == ctx.workspace_id)
    if claim_id:
        load_claim(db, ctx, claim_id)
        query = query.where(AuditEvent.claim_id == claim_id)
    return {
        "items": [
            {
                "id": a.id,
                "claim_id": a.claim_id,
                "actor_id": a.actor_id,
                "action": a.action,
                "detail": a.detail,
                "at": a.created_at.isoformat(),
            }
            for a in db.scalars(query.order_by(AuditEvent.created_at.desc()).limit(200))
        ]
    }


class JobAction(Reason):
    action: Literal["pause", "resume", "reschedule", "query", "retry"]
    expected_status: str
    scheduled_at: datetime | None = None


@router.post("/admin/jobs/{job_id}/actions")
def job_action(
    job_id: str,
    body: JobAction,
    request: Request,
    ctx: Context = Depends(administrator),
    db: Session = Depends(get_db),
):
    def execute():
        scoped(db, Job, job_id, ctx.workspace_id)
        job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
        if job.status != body.expected_status or job.status == "running":
            raise AppError("INVALID_STATE", "任务状态已变化或执行中，请先刷新", 409)
        submission = db.get_one(Submission, job.entity_id) if job.kind == "dispatch" else None
        if body.action == "query":
            if not submission or submission.status != "unknown":
                raise AppError("INVALID_STATE", "仅不确定发送结果可核对", 409)
            result = StubApprovalGateway(ctx.workspace_id).query(submission.id)
            if result:
                confirm_created(db, submission, result, job.payload["actor_id"])
                job.status = "done"
            else:
                submission.failure = "本地Stub尚无创建证据；维持unknown，未重发"
        elif body.action == "pause":
            if job.status != "queued":
                raise AppError("INVALID_STATE", "仅待执行任务可以暂停", 409)
            job.status = "paused"
        elif body.action in {"resume", "reschedule"}:
            if job.status not in {"paused", "queued"}:
                raise AppError("INVALID_STATE", "此状态不允许调时/恢复", 409)
            moment = body.scheduled_at or now()
            if moment.tzinfo is None:
                raise AppError("VALIDATION_ERROR", "时间需带时区", 422)
            job.available_at = (
                business_time(max(moment, now())) if job.payload.get("pooled") else max(moment, now())
            )
            job.status = "queued"
            if submission:
                submission.scheduled_at = job.available_at
        else:
            if job.status != "failed" or job.kind not in {"ledger", "import"}:
                raise AppError(
                    "INVALID_STATE", "此入口只重试明确失败的旁路；Agent请新建任务，unknown必须核对", 409
                )
            job.status, job.error, job.available_at = "queued", "", now()
            job.payload = {**job.payload, "fault": False}
        admin_audit(db, ctx, f"job.{body.action}", body.reason, job_id=job.id)
        return {
            "id": job.id,
            "status": job.status,
            "submission": submission_view(submission) if submission else None,
        }

    return command(
        db,
        ctx,
        request.headers.get("idempotency-key"),
        f"job.action:{job_id}",
        body.model_dump(mode="json"),
        execute,
    )


class SimulatedEvent(Reason):
    expected_state: str
    state: Literal["rejected", "cancelled"]


@router.post("/submissions/{submission_id}/simulated-event")
def simulated_event(
    submission_id: str,
    body: SimulatedEvent,
    request: Request,
    ctx: Context = Depends(administrator),
    db: Session = Depends(get_db),
):
    def execute():
        from .ledger import process_event
        from .models import GatewayResult

        submission = scoped(db, Submission, submission_id, ctx.workspace_id)
        gateway = db.scalars(
            select(GatewayResult).where(GatewayResult.submission_id == submission.id).with_for_update()
        ).one_or_none()
        if not gateway or gateway.status != body.expected_state or gateway.status != "created":
            raise AppError("INVALID_STATE", "当前模拟审批状态不允许此变更", 409)
        gateway.status = body.state
        event = process_event(db, submission.id)
        conflicts = []
        for entry in db.scalars(
            select(LedgerEntry).where(LedgerEntry.event_id == event.id).with_for_update()
        ):
            try:
                rollback_entry(entry)
            except AppError as error:
                conflicts.append({"entry_id": entry.id, "code": error.code, "message": error.message})
        event.issues = [*event.issues, *conflicts]
        event.status = "needs_attention" if conflicts else "rolled_back"
        admin_audit(
            db, ctx, "approval.stub_event", body.reason, submission_id=submission.id, state=body.state
        )
        return {"adapter_mode": "stub", "state": gateway.status, "conflicts": conflicts}

    return command(
        db,
        ctx,
        request.headers.get("idempotency-key"),
        f"stub-event:{submission_id}",
        body.model_dump(),
        execute,
    )


@router.get("/ledger/events")
def ledger_events(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    return {
        "columns": COLUMNS,
        "adapter_mode": "stub",
        "items": [
            {
                "id": e.id,
                "submission_id": e.submission_id,
                "month": e.month,
                "mode": e.mode,
                "status": e.status,
                "candidates": e.candidates,
                "issues": e.issues,
            }
            for e in db.scalars(
                select(LedgerEvent)
                .where(LedgerEvent.workspace_id == ctx.workspace_id)
                .order_by(LedgerEvent.created_at.desc())
                .limit(100)
            )
        ],
    }


@router.get("/ledger/entries")
def ledger_entries(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    return {
        "columns": COLUMNS,
        "adapter_mode": "stub",
        "items": [
            {"id": e.id, "event_id": e.event_id, "values": e.values, "status": e.status}
            for e in db.scalars(select(LedgerEntry).where(LedgerEntry.workspace_id == ctx.workspace_id))
        ],
    }


@router.post("/ledger/events/{event_id}/sync")
def ledger_sync(
    event_id: str, body: Reason, ctx: Context = Depends(administrator), db: Session = Depends(get_db)
):
    # Serialize projection writes in this isolated workspace to deduplicate across events.
    from .models import Workspace

    db.scalars(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update()).one()
    event = scoped(db, LedgerEvent, event_id, ctx.workspace_id)
    sync_event(db, event)
    admin_audit(db, ctx, "ledger.stub_sync", body.reason, event_id=event.id)
    db.commit()
    return {"id": event.id, "status": event.status, "adapter_mode": "stub"}


@router.post("/ledger/entries/{entry_id}/rollback")
def ledger_rollback(
    entry_id: str, body: Reason, ctx: Context = Depends(administrator), db: Session = Depends(get_db)
):
    scoped(db, LedgerEntry, entry_id, ctx.workspace_id)
    entry = db.scalars(select(LedgerEntry).where(LedgerEntry.id == entry_id).with_for_update()).one()
    rollback_entry(entry)
    admin_audit(db, ctx, "ledger.rollback", body.reason, entry_id=entry.id)
    db.commit()
    return {"id": entry.id, "status": entry.status}


class Invitations(Input):
    campaign: str = Field(min_length=1, max_length=100)
    employee_ids: list[str] = Field(min_length=1, max_length=50)


@router.post("/feedback/invitations", status_code=201)
def invite(
    body: Invitations, request: Request, ctx: Context = Depends(administrator), db: Session = Depends(get_db)
):
    def execute():
        result = []
        # Workspace lock covers campaign-recipient uniqueness without leaking tokens to dedup logs.
        from .models import Workspace

        db.scalars(select(Workspace).where(Workspace.id == ctx.workspace_id).with_for_update()).one()
        for employee_id in dict.fromkeys(body.employee_ids):
            employee = scoped(db, Employee, employee_id, ctx.workspace_id)
            invitation = db.scalar(
                select(FeedbackInvitation).where(
                    FeedbackInvitation.workspace_id == ctx.workspace_id,
                    FeedbackInvitation.employee_id == employee.id,
                    FeedbackInvitation.campaign == body.campaign,
                )
            )
            if invitation:
                result.append({"id": invitation.id, "status": invitation.status, "deduplicated": True})
                continue
            token = secrets.token_urlsafe(32)
            invitation = FeedbackInvitation(
                workspace_id=ctx.workspace_id,
                employee_id=employee.id,
                campaign=body.campaign,
                token_hash=token_hash(token),
            )
            db.add(invitation)
            db.flush()
            result.append(
                {
                    "id": invitation.id,
                    "name": employee.name,
                    "status": invitation.status,
                    "url": f"/feedback#token={token}",
                    "adapter_mode": "stub",
                }
            )
        audit(db, ctx, "feedback.simulated_invitation", campaign=body.campaign, count=len(result))
        return {"items": result, "adapter_mode": "stub"}

    # Raw tokens must not enter the generic idempotency store. Campaign+recipient provides command dedup.
    result = execute()
    db.commit()
    return result


@router.get("/feedback/invitations")
def invitations(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(FeedbackInvitation)
        .where(FeedbackInvitation.workspace_id == ctx.workspace_id)
        .order_by(FeedbackInvitation.created_at.desc())
    )
    return {
        "items": [
            {
                "id": i.id,
                "employee_id": i.employee_id,
                "name": db.get_one(Employee, i.employee_id).name,
                "campaign": i.campaign,
                "status": i.status,
                "opened_at": i.opened_at.isoformat() if i.opened_at else None,
                "adapter_mode": "stub",
            }
            for i in rows
        ]
    }


@router.post("/feedback/invitations/{invitation_id}/retry")
def retry_invitation(
    invitation_id: str, body: Reason, ctx: Context = Depends(administrator), db: Session = Depends(get_db)
):
    scoped(db, FeedbackInvitation, invitation_id, ctx.workspace_id)
    invitation = db.scalars(
        select(FeedbackInvitation).where(FeedbackInvitation.id == invitation_id).with_for_update()
    ).one()
    if invitation.status != "failed":
        raise AppError("INVALID_STATE", "只有明确失败的邀请允许重试", 409)
    token = secrets.token_urlsafe(32)
    invitation.token_hash, invitation.status = token_hash(token), "simulated_sent"
    audit(db, ctx, "feedback.retry", invitation_id=invitation.id)
    db.commit()
    return {"id": invitation.id, "url": f"/feedback#token={token}", "adapter_mode": "stub"}


class InvitationToken(Input):
    token: str = Field(min_length=20, max_length=100)


def find_invitation(db, token, lock=False):
    query = select(FeedbackInvitation).where(FeedbackInvitation.token_hash == token_hash(token))
    invitation = db.scalars(query.with_for_update() if lock else query).one_or_none()
    if not invitation:
        raise AppError("RESOURCE_NOT_FOUND", "邀请无效或已更新", 404)
    return invitation


@router.post("/feedback/resolve")
def resolve(body: InvitationToken, db: Session = Depends(get_db)):
    invitation = find_invitation(db, body.token)
    if not invitation.opened_at:
        invitation.opened_at = now()
    answered = bool(db.scalar(select(FeedbackAnswer.id).where(FeedbackAnswer.invitation_id == invitation.id)))
    db.commit()
    return {
        "name": db.get_one(Employee, invitation.employee_id).name,
        "campaign": invitation.campaign,
        "submitted": answered,
        "difficulties": FEEDBACK_DIFFICULTIES,
        "priorities": FEEDBACK_PRIORITIES,
        "identity_note": "此链接仅关联邀请，不代表强实名验证",
        "adapter_mode": "stub",
    }


class AnswerInput(InvitationToken):
    difficulty: str
    priority: str
    suggestion: str = Field(default="", max_length=500)


@router.post("/feedback/answers", status_code=201)
def answer(body: AnswerInput, db: Session = Depends(get_db)):
    if body.difficulty not in FEEDBACK_DIFFICULTIES or body.priority not in FEEDBACK_PRIORITIES:
        raise AppError("VALIDATION_ERROR", "请选择有效的问卷选项", 422)
    invitation = find_invitation(db, body.token, lock=True)
    existing = db.scalar(select(FeedbackAnswer).where(FeedbackAnswer.invitation_id == invitation.id))
    if existing:
        return {"id": existing.id, "status": "submitted", "deduplicated": True}
    entry = FeedbackAnswer(
        workspace_id=invitation.workspace_id,
        invitation_id=invitation.id,
        difficulty=body.difficulty,
        priority=body.priority,
        suggestion=body.suggestion,
    )
    invitation.status = "submitted"
    db.add(entry)
    db.commit()
    return {"id": entry.id, "status": "submitted"}


@router.get("/feedback/answers")
def answers(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(FeedbackAnswer)
        .where(FeedbackAnswer.workspace_id == ctx.workspace_id)
        .order_by(FeedbackAnswer.created_at.desc())
    )
    return {
        "items": [
            {
                "id": a.id,
                "invitation_id": a.invitation_id,
                "difficulty": a.difficulty,
                "priority": a.priority,
                "suggestion": a.suggestion,
            }
            for a in rows
        ]
    }


@router.get("/feedback/export")
def export_feedback(ctx: Context = Depends(administrator), db: Session = Depends(get_db)):
    import csv
    from io import StringIO

    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["邀请编号", "困难", "优先改进", "建议"])
    for row in answers(ctx, db)["items"]:
        # Spreadsheet formulas are text in a feedback export.
        writer.writerow(
            [
                ("'" + v) if str(v).startswith(("=", "+", "-", "@")) else v
                for v in [row["invitation_id"], row["difficulty"], row["priority"], row["suggestion"]]
            ]
        )
    return Response(
        stream.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="feedback.csv"'},
    )
