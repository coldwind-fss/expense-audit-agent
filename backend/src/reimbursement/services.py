import hashlib
import json
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import now
from .errors import AppError
from .models import (
    AuditEvent,
    Claim,
    ClaimLine,
    ClaimRevision,
    Employee,
    IdempotencyRecord,
    Material,
    ReviewReport,
)
from .security import Context


def money(value) -> str | None:
    return None if value is None else format(Decimal(str(value)), ".2f")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def scoped(db: Session, model, entity_id: str, workspace_id: str):
    row = db.scalar(select(model).where(model.id == entity_id, model.workspace_id == workspace_id))
    if row is None:
        raise AppError("RESOURCE_NOT_FOUND", "记录不存在或无权访问", 404)
    return row


def load_claim(db: Session, context: Context, claim_id: str, *, edit=False, lock=False) -> Claim:
    statement = select(Claim).where(Claim.id == claim_id, Claim.workspace_id == context.workspace_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    claim = db.scalar(statement)
    if not claim or (claim.actor_id != context.actor.id and context.actor.role != "admin"):
        raise AppError("RESOURCE_NOT_FOUND", "报销不存在或无权访问", 404)
    if edit and claim.status != "draft":
        raise AppError("INVALID_STATE", "已提交报销不能直接修改，请撤销并复制或新建", 409)
    if edit and claim.actor_id != context.actor.id and len(context.action_reason.strip()) < 4:
        raise AppError("ACTION_REASON_REQUIRED", "协助修改其他操作人的报销，需要填写至少4字符的处理原因", 422)
    return claim


def check_revision(claim: Claim, expected: int):
    if claim.revision != expected:
        raise AppError(
            "REVISION_CONFLICT",
            "报销已发生变化，保留您的输入后请刷新核对",
            409,
            [{"path": "expected_revision", "current_revision": claim.revision}],
        )


def material_view(material: Material) -> dict:
    return {
        "id": material.id,
        "claim_id": material.claim_id,
        "name": material.name,
        "media_type": material.media_type,
        "size": material.size,
        "kind": material.kind,
        "line_id": material.line_id,
        "status": material.status,
        "error": material.error,
        "facts": material.facts,
        "fact_version": material.fact_version,
        "manual_amount": money(material.manual_amount),
        "duplicate_of": material.duplicate_of,
        "duplicate_kind": material.duplicate_kind,
        "duplicate_decision": material.duplicate_decision,
        "page_count": len(material.pages),
    }


def claim_view(db: Session, claim: Claim) -> dict:
    lines = db.scalars(
        select(ClaimLine)
        .where(ClaimLine.claim_id == claim.id)
        .order_by(ClaimLine.position, ClaimLine.created_at)
    ).all()
    materials = db.scalars(
        select(Material)
        .where(Material.claim_id == claim.id, Material.status != "deleted")
        .order_by(Material.created_at)
    ).all()
    people = {x: db.get_one(Employee, x) for x in [claim.actor_id, claim.subject_id, claim.originator_id]}
    latest = db.scalar(
        select(ReviewReport.id)
        .where(ReviewReport.claim_id == claim.id)
        .order_by(ReviewReport.created_at.desc())
        .limit(1)
    )
    return {
        "id": claim.id,
        "revision": claim.revision,
        "title": claim.title,
        "workflow_key": claim.workflow_key,
        "route_mode": claim.route_mode,
        "actor_id": claim.actor_id,
        "subject_id": claim.subject_id,
        "originator_id": claim.originator_id,
        "actor_name": people[claim.actor_id].name,
        "subject_name": people[claim.subject_id].name,
        "originator_name": people[claim.originator_id].name,
        "department_id": claim.department_id,
        "company_id": claim.company_id,
        "social_company_id": people[claim.subject_id].social_company_id,
        "account_id": claim.account_id,
        "total_amount": money(claim.total_amount),
        "total_auto": claim.total_auto,
        "related_ids": claim.related_ids,
        "remark": claim.remark,
        "travel_date_remark": claim.travel_date_remark,
        "status": claim.status,
        "updated_at": claim.updated_at.isoformat(),
        "lines": [
            {
                "id": line.id,
                "business_date": line.business_date.isoformat() if line.business_date else None,
                "reason": line.reason,
                "amount": money(line.amount),
                "project": line.project,
                "expense_type": line.expense_type,
                "invoice_type": line.invoice_type,
                "related_id": line.related_id,
                "remark": line.remark,
                "sources": line.sources,
            }
            for line in lines
        ],
        "materials": [material_view(m) for m in materials],
        "latest_review_id": latest,
    }


def audit(db: Session, context: Context, action: str, claim_id: str | None = None, **detail):
    if context.action_reason:
        detail.setdefault("admin_reason", context.action_reason)
    db.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor_id=context.actor.id,
            claim_id=claim_id,
            action=action,
            detail=jsonable_encoder(detail),
        )
    )


def bump_claim(db: Session, context: Context, claim: Claim, action: str):
    db.flush()
    claim.revision += 1
    claim.updated_at = now()
    db.execute(
        update(ReviewReport)
        .where(ReviewReport.claim_id == claim.id, ReviewReport.valid.is_(True))
        .values(valid=False)
    )
    db.flush()
    db.add(
        ClaimRevision(
            workspace_id=claim.workspace_id,
            claim_id=claim.id,
            revision=claim.revision,
            snapshot=claim_view(db, claim),
        )
    )
    audit(
        db,
        context,
        action,
        claim.id,
        revision=claim.revision,
        **({"admin_reason": context.action_reason} if context.action_reason else {}),
    )


def command(db: Session, context: Context, key: str | None, scope: str, payload: Any, execute):
    if not key or len(key) > 150:
        raise AppError("INVALID_REQUEST", "此操作需要有效的Idempotency-Key", 400)
    fingerprint = digest(payload)
    lookup = select(IdempotencyRecord).where(
        IdempotencyRecord.workspace_id == context.workspace_id,
        IdempotencyRecord.actor_id == context.actor.id,
        IdempotencyRecord.scope == scope,
        IdempotencyRecord.key == key,
    )
    record = db.scalar(lookup)
    if record is None:
        try:
            with db.begin_nested():
                record = IdempotencyRecord(
                    workspace_id=context.workspace_id,
                    actor_id=context.actor.id,
                    scope=scope,
                    key=key,
                    request_hash=fingerprint,
                )
                db.add(record)
                db.flush()
        except IntegrityError:
            record = db.scalars(lookup).one()
    if record.request_hash != fingerprint:
        raise AppError("IDEMPOTENCY_CONFLICT", "该操作编号已经用于不同内容", 409)
    if record.result:
        return record.result
    result = jsonable_encoder(execute(), custom_encoder={Decimal: money})
    record.result = result
    db.commit()
    return result
