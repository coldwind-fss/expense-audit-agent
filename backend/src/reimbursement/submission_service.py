from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .agent_service import review_signature, review_snapshot, worker_context
from .config import settings
from .db import SessionLocal, now
from .errors import AppError
from .models import DispatchGuard, GatewayResult, Job, ReviewReport, Submission
from .rules import evaluate
from .services import audit, check_revision, load_claim, scoped

SHANGHAI = ZoneInfo("Asia/Shanghai")


def release_time(moment: datetime, enabled: bool) -> datetime:
    if not enabled:
        return moment
    local = moment.astimezone(SHANGHAI)
    if 21 <= local.day <= 25:
        return moment
    year, month = local.year, local.month
    if local.day >= 26:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return datetime(year, month, 21, 9, tzinfo=SHANGHAI)


def business_time(moment: datetime) -> datetime:
    local = moment.astimezone(SHANGHAI)
    if local.hour < 9:
        return local.replace(hour=9, minute=0, second=0, microsecond=0)
    if local.hour >= 18:
        return (local + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return moment


def submission_view(row):
    return {
        "id": row.id,
        "claim_id": row.claim_id,
        "title": row.snapshot.get("claim", {}).get("title", ""),
        "workflow_key": row.snapshot.get("claim", {}).get("workflow_key"),
        "status": row.status,
        "dispatch_status": row.status,
        "total_amount": row.snapshot.get("claim", {}).get("total_amount"),
        "scheduled_at": row.scheduled_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "dispatched_at": row.dispatched_at.isoformat() if row.dispatched_at else None,
        "adapter_mode": "stub",
        "external_instance_id": None,
        "external_state": "simulated_created" if row.status == "succeeded" else "not_created",
        "enterprise_connected": False,
        "simulated_reference": row.simulated_reference,
        "failure": row.failure,
        "downstream": "manual_approval"
        if row.snapshot.get("claim", {}).get("workflow_key") == "no_invoice"
        else "configured_auto_approval",
    }


def create_submission(db, ctx, claim_id, expected_revision, review_id, reason=""):
    claim = load_claim(db, ctx, claim_id, lock=True)
    existing = db.scalar(select(Submission).where(Submission.claim_id == claim.id))
    if existing:
        return submission_view(existing)
    check_revision(claim, expected_revision)
    if claim.status != "draft":
        raise AppError("INVALID_STATE", "该报销已锁定", 409)
    report = scoped(db, ReviewReport, review_id, ctx.workspace_id)
    snapshot = review_snapshot(db, ctx, claim)
    if (
        report.claim_id != claim.id
        or not report.valid
        or report.input_revision != claim.revision
        or report.input_signature != review_signature(snapshot)
    ):
        raise AppError("RESULT_OUTDATED", "审核报告已失效，请重新审核", 409)
    result = evaluate(snapshot)
    if not report.can_submit or not result["can_submit"]:
        raise AppError("SUBMISSION_BLOCKED", "当前申报未通过完整核验", 422, result["checks"])
    from .api_claims import ensure_workflow

    ensure_workflow(ctx, claim.workflow_key)
    if claim.route_mode == "admin_originator" and ctx.actor.role != "admin":
        raise AppError("FORBIDDEN", "管理员代发需要管理员权限", 403)
    if claim.route_mode == "admin_originator" or claim.actor_id != ctx.actor.id:
        if len(reason.strip()) < 4:
            raise AppError("ACTION_REASON_REQUIRED", "管理员提交需要明确处理原因", 422)
    snapshot.update(
        base_revision=claim.revision,
        input_signature=report.input_signature,
        schema_version="submission.v1",
        reviewed_by=report.run_id,
    )
    scheduled = release_time(now(), settings().scheduling_enabled)
    submission = Submission(
        workspace_id=ctx.workspace_id,
        claim_id=claim.id,
        review_id=report.id,
        snapshot=snapshot,
        scheduled_at=scheduled,
    )
    db.add(submission)
    db.flush()
    db.add(
        Job(
            workspace_id=ctx.workspace_id,
            kind="dispatch",
            entity_id=submission.id,
            available_at=scheduled,
            payload={
                "actor_id": ctx.actor.id,
                "pooled": settings().scheduling_enabled and not 21 <= now().astimezone(SHANGHAI).day <= 25,
            },
        )
    )
    claim.status = "submitted"
    claim.updated_at = now()
    if claim.route_mode == "admin_originator" or claim.actor_id != ctx.actor.id:
        from .models import AdminAction, SupportCase

        case = db.scalar(select(SupportCase).where(SupportCase.claim_id == claim.id))
        if case:
            case.status = "submitted"
        db.add(
            AdminAction(
                workspace_id=ctx.workspace_id,
                actor_id=ctx.actor.id,
                case_id=case.id if case else None,
                action="approval.submit",
                reason=reason,
                detail={"submission_id": submission.id},
            )
        )
    audit(
        db,
        ctx,
        "submission.accepted",
        claim.id,
        submission_id=submission.id,
        adapter_mode="stub",
        base_revision=claim.revision,
    )
    return submission_view(submission)


class StubApprovalGateway:
    """A durable command-id result; no network calls or enterprise credentials."""

    def __init__(self, workspace_id):
        self.workspace_id = workspace_id

    def query(self, command_id):
        with SessionLocal() as db:
            result = db.scalar(
                select(GatewayResult).where(
                    GatewayResult.submission_id == command_id, GatewayResult.workspace_id == self.workspace_id
                )
            )
            return {"reference": result.simulated_reference, "status": result.status} if result else None

    def submit(self, command_id, snapshot):
        with SessionLocal() as db:
            # Stable command_id is also protected by the gateway_results unique constraint.
            reference = f"SIM-{command_id.upper()}"
            db.execute(
                insert(GatewayResult)
                .values(
                    workspace_id=self.workspace_id, submission_id=command_id, simulated_reference=reference
                )
                .on_conflict_do_nothing(index_elements=[GatewayResult.submission_id])
            )
            db.commit()
        return self.query(command_id)


def confirm_created(db, submission, result, actor_id):
    submission.status, submission.failure = "succeeded", ""
    submission.simulated_reference, submission.dispatched_at = result["reference"], now()
    existing = db.scalar(select(Job).where(Job.kind == "ledger", Job.entity_id == submission.id))
    if not existing:
        db.add(
            Job(
                workspace_id=submission.workspace_id,
                kind="ledger",
                entity_id=submission.id,
                payload={"actor_id": actor_id, "fault": submission.fault == "sidecar_failure"},
            )
        )
    ctx = worker_context(db, submission.workspace_id, actor_id)
    audit(
        db,
        ctx,
        "submission.simulated_created",
        submission.claim_id,
        reference=result["reference"],
        adapter_mode="stub",
    )


def dispatch(job_id, token, moment=None):
    moment = moment or now()
    with SessionLocal() as db:
        job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
        if job.lease_token != token or job.status != "running":
            return
        submission = db.scalars(
            select(Submission).where(Submission.id == job.entity_id).with_for_update()
        ).one()
        if submission.status in {"succeeded", "unknown", "cancelled", "manual"}:
            job.status = "done" if submission.status == "succeeded" else submission.status
            db.commit()
            return
        snapshot = submission.snapshot
        if snapshot.get("schema_version") != "submission.v1" or not snapshot.get("base_revision"):
            submission.status, submission.failure, job.status = (
                "manual",
                "历史快照不兼容，请人工核对",
                "manual",
            )
            db.commit()
            return
        db.execute(
            insert(DispatchGuard)
            .values(workspace_id=job.workspace_id, next_allowed_at=moment)
            .on_conflict_do_nothing(index_elements=[DispatchGuard.workspace_id])
        )
        guard = db.scalars(
            select(DispatchGuard).where(DispatchGuard.workspace_id == job.workspace_id).with_for_update()
        ).one()
        if guard.paused:
            job.status, job.available_at = "queued", moment + timedelta(seconds=30)
            db.commit()
            return
        if job.payload.get("pooled"):
            first = db.scalar(
                select(Job.id)
                .where(
                    Job.workspace_id == job.workspace_id,
                    Job.kind == "dispatch",
                    Job.status.in_(["queued", "running"]),
                    Job.payload["pooled"].as_boolean().is_(True),
                )
                .order_by(Job.created_at, Job.id)
                .limit(1)
            )
            if first != job.id:
                job.status, job.available_at = (
                    "queued",
                    business_time(max(moment + timedelta(minutes=3), guard.next_allowed_at)),
                )
                db.commit()
                return
            allowed = business_time(max(moment, guard.next_allowed_at))
            if allowed > moment:
                job.status, job.available_at = "queued", allowed
                db.commit()
                return
            guard.next_allowed_at = moment + timedelta(minutes=3)
        submission.status = "dispatching"
        workspace_id, command_id, actor_id, fault = (
            job.workspace_id,
            submission.id,
            job.payload["actor_id"],
            submission.fault,
        )
        db.commit()
    gateway = StubApprovalGateway(workspace_id)
    # Transport outcomes are deliberately classified before retry/query decisions.
    if fault == "before_failure":
        result, error = None, "创建前明确临时失败"
    else:
        result = gateway.submit(command_id, snapshot)
        error = "创建响应超时，结果待核对" if fault == "after_timeout" else ""
    with SessionLocal() as db:
        job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
        if job.lease_token != token or job.status != "running":
            return
        submission = db.get_one(Submission, command_id)
        if fault == "after_timeout":
            submission.status, submission.failure, job.status = "unknown", error, "unknown"
        elif error:
            submission.status, submission.failure = ("retry" if job.attempts < 3 else "manual"), error
            job.status = "queued" if job.attempts < 3 else "manual"
            job.available_at = now() + timedelta(seconds=30 * job.attempts)
        else:
            confirm_created(db, submission, result, actor_id)
            job.status = "done"
        job.lease_until = None
        db.commit()
