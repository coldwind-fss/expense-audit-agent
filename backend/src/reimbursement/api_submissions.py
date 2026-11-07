from copy import deepcopy

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .errors import AppError
from .models import Claim, ClaimLine, ClaimRevision, GatewayResult, Job, Material, Submission
from .schemas import RevisionInput
from .security import Context, current_context
from .services import audit, check_revision, claim_view, command, load_claim, scoped
from .submission_service import create_submission, submission_view

router = APIRouter(prefix="/api/v1")


class SubmitInput(RevisionInput):
    review_id: str
    reason: str = ""


@router.post("/claims/{claim_id}/submissions", status_code=202)
def submit(
    claim_id: str,
    body: SubmitInput,
    request: Request,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    return command(
        db,
        ctx,
        request.headers.get("idempotency-key"),
        f"submission:{claim_id}",
        body.model_dump(),
        lambda: create_submission(db, ctx, claim_id, body.expected_revision, body.review_id, body.reason),
    )


@router.get("/submissions")
def history(cursor: int = 0, ctx: Context = Depends(current_context), db: Session = Depends(get_db)):
    query = (
        select(Submission)
        .join(Claim, Claim.id == Submission.claim_id)
        .where(Submission.workspace_id == ctx.workspace_id)
    )
    if ctx.actor.role != "admin":
        query = query.where(Claim.actor_id == ctx.actor.id)
    rows = db.scalars(query.order_by(Submission.created_at.desc()).offset(max(0, cursor)).limit(51)).all()
    return {
        "items": [submission_view(x) for x in rows[:50]],
        "has_more": len(rows) > 50,
        "next_cursor": cursor + 50 if len(rows) > 50 else None,
    }


@router.get("/submissions/{submission_id}")
def get_submission(
    submission_id: str, ctx: Context = Depends(current_context), db: Session = Depends(get_db)
):
    submission = scoped(db, Submission, submission_id, ctx.workspace_id)
    load_claim(db, ctx, submission.claim_id)
    gateway = db.scalar(select(GatewayResult).where(GatewayResult.submission_id == submission.id))
    return {
        **submission_view(submission),
        "snapshot": submission.snapshot,
        "simulated_approval_state": gateway.status if gateway else "not_created",
    }


class CancelCopy(RevisionInput):
    expected_status: str


@router.post("/submissions/{submission_id}/cancel-and-copy", status_code=201)
def cancel_copy(
    submission_id: str,
    body: CancelCopy,
    request: Request,
    ctx: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    def execute():
        old = scoped(db, Submission, submission_id, ctx.workspace_id)
        claim = load_claim(db, ctx, old.claim_id, lock=True)
        check_revision(claim, body.expected_revision)
        job = db.scalars(
            select(Job).where(Job.kind == "dispatch", Job.entity_id == old.id).with_for_update()
        ).one()
        db.refresh(old)
        if (
            old.status != body.expected_status
            or old.status not in {"scheduled", "retry", "manual"}
            or job.status == "running"
        ):
            raise AppError("INVALID_STATE", "当前状态不能撤销复制；unknown需先核对", 409)
        old.status, job.status, claim.status = "cancelled", "cancelled", "cancelled"
        fields = {
            k: deepcopy(getattr(claim, k))
            for k in [
                "title",
                "workflow_key",
                "route_mode",
                "actor_id",
                "subject_id",
                "originator_id",
                "department_id",
                "company_id",
                "account_id",
                "total_amount",
                "total_auto",
                "related_ids",
                "remark",
                "travel_date_remark",
            ]
        }
        if fields["total_auto"]:
            fields.update(total_auto=False, total_amount=None)
        new = Claim(workspace_id=ctx.workspace_id, **fields)
        db.add(new)
        db.flush()
        line_ids = {}
        for line in db.scalars(select(ClaimLine).where(ClaimLine.claim_id == claim.id)):
            values = {
                k: deepcopy(getattr(line, k))
                for k in [
                    "position",
                    "business_date",
                    "reason",
                    "amount",
                    "project",
                    "expense_type",
                    "invoice_type",
                    "related_id",
                    "remark",
                    "sources",
                ]
            }
            line_copy = ClaimLine(workspace_id=ctx.workspace_id, claim_id=new.id, **values)
            db.add(line_copy)
            db.flush()
            line_ids[line.id] = line_copy.id
        material_ids = {}
        material_copies = []
        for material in db.scalars(
            select(Material).where(Material.claim_id == claim.id, Material.status != "deleted")
        ):
            values = {
                k: deepcopy(getattr(material, k))
                for k in [
                    "name",
                    "content_hash",
                    "storage_key",
                    "media_type",
                    "size",
                    "kind",
                    "status",
                    "error",
                    "pages",
                    "fixture_data",
                    "facts",
                    "fact_version",
                    "manual_amount",
                    "duplicate_kind",
                    "duplicate_decision",
                ]
            }
            copy = Material(
                workspace_id=ctx.workspace_id,
                claim_id=new.id,
                line_id=line_ids.get(material.line_id or ""),
                **values,
            )
            db.add(copy)
            db.flush()
            material_ids[material.id] = copy.id
            material_copies.append((material, copy))
        for original, copy in material_copies:
            copy.duplicate_of = material_ids.get(original.duplicate_of or "")
            copy.facts = {
                **copy.facts,
                "evidence_refs": [{**r, "material_id": copy.id} for r in copy.facts.get("evidence_refs", [])],
            }
        db.flush()
        db.add(
            ClaimRevision(
                workspace_id=ctx.workspace_id, claim_id=new.id, revision=1, snapshot=claim_view(db, new)
            )
        )
        audit(db, ctx, "submission.cancelled_and_copied", claim.id, new_claim_id=new.id)
        return claim_view(db, new)

    return command(
        db,
        ctx,
        request.headers.get("idempotency-key"),
        f"cancel-copy:{submission_id}",
        body.model_dump(),
        execute,
    )
