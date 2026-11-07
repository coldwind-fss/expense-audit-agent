from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalogs import canonical_invoice_type
from .config import settings
from .db import now, uid
from .errors import AppError
from .model_gateway import model_profile
from .models import (
    Account,
    AgentRun,
    AgentStep,
    Claim,
    Company,
    Employee,
    Job,
    Material,
    MaterialFact,
    RelatedApproval,
    ReviewReport,
    SessionRecord,
    SuggestionBatch,
)
from .rules import (
    POLICY_VERSION,
    amount,
    effective_invoice,
    effective_payment,
    normalize_facts,
    sync_line_amounts,
)
from .security import Context
from .services import audit, bump_claim, claim_view, digest, load_claim, scoped


def worker_context(db: Session, workspace_id: str, actor_id: str) -> Context:
    actor = scoped(db, Employee, actor_id, workspace_id)
    return Context(SessionRecord(workspace_id=workspace_id, employee_id=actor.id), actor)


def review_snapshot(db: Session, context: Context, claim: Claim) -> dict:
    view = claim_view(db, claim)
    selected_ids = set(claim.related_ids) | {
        line["related_id"] for line in view["lines"] if line["related_id"]
    }
    approvals = db.scalars(
        select(RelatedApproval).where(
            RelatedApproval.workspace_id == claim.workspace_id, RelatedApproval.id.in_(selected_ids)
        )
    ).all()
    companies = db.scalars(select(Company).where(Company.workspace_id == claim.workspace_id)).all()
    account = db.get_one(Account, claim.account_id) if claim.account_id else None
    return {
        "actor_id": context.actor.id,
        "claim": view,
        "companies": [{"id": x.id, "name": x.name} for x in companies],
        "approvals": [
            {
                "id": x.id,
                "employee_id": x.employee_id,
                "approval_type": x.approval_type,
                "start_date": str(x.start_date),
                "end_date": str(x.end_date),
                "status": x.status,
            }
            for x in approvals
        ],
        "account_valid": bool(account and account.workspace_id == claim.workspace_id),
        "policy_version": POLICY_VERSION,
        "execution_mode": settings().model_mode,
    }


def review_signature(snapshot: dict) -> str:
    claim = snapshot["claim"]
    return digest(
        {
            "claim_id": claim["id"],
            "revision": claim["revision"],
            "facts": [(m["id"], m["fact_version"]) for m in claim["materials"]],
            "policy": POLICY_VERSION,
            "mode": settings().model_mode,
            "graph": "reimbursement.v2.1",
            "model_profile": model_profile(),
        }
    )


def accepted(run: AgentRun) -> dict:
    return {
        "run_id": run.id,
        "task_kind": run.task_kind,
        "status": run.status,
        "input_revision": run.input_revision,
        "execution_mode": run.execution_mode,
        "poll_after_ms": 1000,
    }


def start_run(
    db: Session, context: Context, claim: Claim, task_kind: str, material: Material | None = None
) -> AgentRun:
    snapshot: dict
    if task_kind == "material_extract":
        if material is None:
            raise AppError("INVALID_REQUEST", "识别任务缺少材料", 400)
        snapshot = {
            "actor_id": context.actor.id,
            "workflow_key": claim.workflow_key,
            "material": {
                "id": material.id,
                "name": material.name,
                "content_hash": material.content_hash,
                "pages": material.pages,
                "kind": material.kind,
                "fixture_data": material.fixture_data if settings().model_mode == "fixture" else {},
            },
        }
        signature = digest(
            {
                "material_id": material.id,
                "content": material.content_hash,
                "mode": settings().model_mode,
                "schema": "material.v1",
                "model_profile": model_profile(),
            }
        )
    else:
        snapshot = review_snapshot(db, context, claim)
        if settings().model_mode == "provider" and any(
            m["status"] == "recognized"
            and m["kind"] != "other"
            and m["facts"].get("execution_mode") != "provider"
            for m in snapshot["claim"]["materials"]
        ):
            raise AppError(
                "FACT_MODE_MISMATCH", "当前包含合成模式的缓存事实，请先在真实模型模式重新识别这些材料", 422
            )
        signature = review_signature(snapshot)
    snapshot["model_profile"] = model_profile()
    snapshot["workspace_id"] = context.workspace_id
    previous = db.scalar(
        select(AgentRun)
        .where(
            AgentRun.claim_id == claim.id,
            AgentRun.task_kind == task_kind,
            AgentRun.input_signature == signature,
            AgentRun.status.in_(["queued", "running", "waiting_input", "completed"]),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    if previous:
        return previous
    count = db.scalars(select(AgentRun.id).where(AgentRun.workspace_id == context.workspace_id)).all()
    if len(count) >= 200:
        raise AppError("MODEL_BUDGET_LIMIT", "当前体验空间的任务额度已用完", 429)
    run = AgentRun(
        workspace_id=context.workspace_id,
        claim_id=claim.id,
        material_id=material.id if material else None,
        task_kind=task_kind,
        input_revision=claim.revision,
        input_signature=signature,
        snapshot=snapshot,
        attempt_id=uid(),
        execution_mode=settings().model_mode,
    )
    db.add(run)
    db.flush()
    db.add(
        Job(
            workspace_id=context.workspace_id,
            kind="agent",
            entity_id=run.id,
            payload={"actor_id": context.actor.id},
        )
    )
    audit(db, context, "agent.queued", claim.id, run_id=run.id, task_kind=task_kind)
    return run


def suggestions(snapshot: dict) -> list[dict]:
    result = []
    claim = snapshot["claim"]
    for line in claim["lines"]:
        mats = [m for m in claim["materials"] if m["line_id"] == line["id"] and m["status"] == "recognized"]
        payments = [m for m in mats if m["kind"] == "payment"]
        invoices = [m for m in mats if m["kind"] == "invoice"]
        total = sum(
            (
                effective_invoice(m) if claim["workflow_key"] == "supply_chain" else effective_payment(m)
                for m in mats
            ),
            Decimal("0"),
        )
        date_materials = payments or invoices
        dates = {m["facts"].get("business_date") for m in date_materials if m["facts"].get("business_date")}
        types = {
            canonical_invoice_type(m["facts"].get("invoice_type", ""), m["facts"].get("document_role", ""))
            for m in invoices
        }
        types.discard("")
        categories = {m["facts"].get("expense_type") for m in mats if m["facts"].get("expense_type")}
        proposed = {
            "amount": amount(total) if total > 0 else None,
            "business_date": next(iter(dates)) if len(dates) == 1 else None,
            "invoice_type": "无"
            if claim["workflow_key"] == "no_invoice"
            else (next(iter(types)) if len(types) == 1 else None),
        }
        if claim["workflow_key"] == "travel":
            proposed["expense_type"] = next(iter(categories)) if len(categories) == 1 else None
        for field, value in proposed.items():
            if value is None or str(line.get(field) or "") == str(value):
                continue
            result.append(
                {
                    "line_id": line["id"],
                    "field": field,
                    "value": value,
                    "previous_value": line.get(field),
                    "previous_source": line["sources"].get(field, {}),
                    "protected": line["sources"].get(field, {}).get("kind") in {"manual", "import"},
                    "evidence_refs": [m["id"] for m in mats],
                    "source_description": "已分配付款凭证"
                    if field == "amount"
                    else "已分配材料；请核对日期/票种含义",
                }
            )
    return result


def publish(db: Session, context: Context, run: AgentRun, job_id: str, lease_token: str, output: dict):
    claim = load_claim(db, context, run.claim_id, lock=True)
    job = db.scalars(
        select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True)
    ).one()
    if not job or job.lease_token != lease_token or job.status != "running":
        return
    db.refresh(run)
    if run.status in {"cancelled", "outdated"} or claim.status != "draft":
        job.status = "done"
        if run.status != "cancelled":
            run.status = "outdated"
        return
    if run.task_kind != "material_extract" and (
        claim.revision != run.input_revision
        or review_signature(review_snapshot(db, context, claim)) != run.input_signature
    ):
        run.status, run.stop_reason, job.status = "outdated", "input_changed", "done"
        return
    if run.task_kind == "material_extract":
        material = db.get_one(Material, run.material_id)
        if (
            not material
            or material.status == "deleted"
            or material.content_hash != run.snapshot["material"]["content_hash"]
        ):
            run.status, job.status = "outdated", "done"
            return
        facts = normalize_facts(output["facts"], material.id, execution_mode=run.execution_mode)
        facts["model_profile"] = run.snapshot.get("model_profile", {})
        facts["prompt_version"] = f"{run.task_kind}.v2.1" if run.execution_mode == "provider" else f"{run.task_kind}.v1"
        material.facts, material.fact_version = facts, material.fact_version + 1
        material.status, material.error = "recognized", ""
        role = facts["document_role"]
        material.kind = (
            "invoice"
            if role in {"tax_invoice", "title_exempt_transport_receipt"}
            else ("other" if role == "supporting_document" else "payment")
        )
        others = db.scalars(
            select(Material)
            .where(Material.claim_id == claim.id, Material.id != material.id, Material.status == "recognized")
            .order_by(Material.created_at)
        ).all()
        material.duplicate_of, material.duplicate_kind = None, ""
        identity = facts.get("invoice_number") or facts.get("transaction_id")
        for other in others:
            if other.kind != material.kind:
                continue
            other_identity = other.facts.get("invoice_number") or other.facts.get("transaction_id")
            if identity and identity == other_identity:
                material.duplicate_of, material.duplicate_kind = other.id, "exact"
                break
            # Uncertain same-amount/merchant/date observations require a human decision.
            # Distinct known transaction IDs are affirmative evidence of different payments.
            if (
                not (identity and other_identity)
                and facts.get("merchant")
                and facts.get("merchant") == other.facts.get("merchant")
                and facts.get("business_date") == other.facts.get("business_date")
                and facts.get("countable_amount") == other.facts.get("countable_amount")
            ):
                material.duplicate_of, material.duplicate_kind = other.id, "possible"
        db.add(
            MaterialFact(
                workspace_id=run.workspace_id,
                material_id=material.id,
                version=material.fact_version,
                facts=facts,
                run_id=run.id,
            )
        )
        sync_line_amounts(db, claim)
        bump_claim(db, context, claim, "material.recognized")
        run.output = {
            "material_id": material.id,
            "fact_version": material.fact_version,
            "execution_mode": run.execution_mode,
        }
    elif run.task_kind == "line_suggest":
        batch = SuggestionBatch(
            workspace_id=run.workspace_id,
            claim_id=claim.id,
            run_id=run.id,
            input_revision=run.input_revision,
            items=suggestions(run.snapshot),
        )
        db.add(batch)
        db.flush()
        run.output = {"batch_id": batch.id, "suggestion_count": len(batch.items)}
    else:
        report = ReviewReport(
            workspace_id=run.workspace_id,
            claim_id=claim.id,
            run_id=run.id,
            input_revision=run.input_revision,
            input_signature=run.input_signature,
            can_submit=output["review"]["can_submit"],
            checks=output["review"]["checks"],
            summary=output["review"]["summary"],
            execution_mode=run.execution_mode,
        )
        db.add(report)
        db.flush()
        run.output = {"report_id": report.id}
    run.status, run.stop_reason, run.finished_at = "completed", "task_complete", now()
    job.status, job.lease_until = "done", None
    audit(db, context, "agent.completed", claim.id, run_id=run.id, task_kind=run.task_kind, output=run.output)


def step_record(db: Session, run: AgentRun, node: str, detail: dict):
    db.add(
        AgentStep(
            workspace_id=run.workspace_id,
            run_id=run.id,
            node=node,
            detail={**detail, "attempt_id": run.attempt_id},
        )
    )
