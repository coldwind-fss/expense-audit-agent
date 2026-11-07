"""Invoice audit and a local, explicitly simulated projection."""

from copy import deepcopy
from decimal import Decimal

from sqlalchemy import select

from .errors import AppError
from .models import GatewayResult, LedgerEntry, LedgerEvent, Submission
from .rules import amount, decimal
from .submission_service import SHANGHAI

COLUMNS = [
    "序号",
    "票号",
    "销方税号",
    "销方名称",
    "购方税号",
    "购方名称",
    "开票日",
    "项目名称",
    "金额",
    "税额",
    "价税合计",
    "入账时间",
    "是否入账",
]


def invoice_candidates(snapshot):
    candidates: list[dict] = []
    issues: list[dict] = []
    seen = set()
    for material in snapshot["claim"]["materials"]:
        facts = material["facts"]
        role = facts.get("document_role")
        if (
            material["kind"] != "invoice"
            or role not in {"tax_invoice", "title_exempt_transport_receipt"}
            or material.get("duplicate_of")
        ):
            continue
        required = ["invoice_number", "buyer_name", "invoice_date", "item_name", "amount"]
        if role == "tax_invoice":
            required += ["seller_tax_number", "seller_name", "net_amount", "tax_amount"]
        missing = [key for key in required if facts.get(key) in (None, "")]
        if missing:
            issues.append({"material_id": material["id"], "code": "MISSING_FIELDS", "fields": missing})
            continue
        if role == "tax_invoice" and abs(
            decimal(facts["net_amount"]) + decimal(facts["tax_amount"]) - decimal(facts["amount"])
        ) > Decimal("0.01"):
            issues.append({"material_id": material["id"], "code": "AMOUNT_TAX_MISMATCH"})
            continue
        fingerprint = f"{facts.get('seller_tax_number', '')}:{facts['invoice_number']}"
        if fingerprint in seen:
            issues.append({"material_id": material["id"], "code": "DUPLICATE_IN_EVENT"})
            continue
        seen.add(fingerprint)
        values = [
            len(candidates) + 1,
            facts["invoice_number"],
            facts.get("seller_tax_number", ""),
            facts.get("seller_name", ""),
            facts.get("buyer_tax_number", ""),
            facts["buyer_name"],
            facts["invoice_date"],
            facts["item_name"],
            amount(facts["net_amount"]) if facts.get("net_amount") is not None else "",
            amount(facts["tax_amount"]) if facts.get("tax_amount") is not None else "",
            amount(facts["amount"]),
            "",
            "否",
        ]
        candidates.append(
            {"material_id": material["id"], "fingerprint": fingerprint, "role": role, "values": values}
        )
    return candidates, issues


def process_event(db, submission_id):
    submission = db.get_one(Submission, submission_id)
    existing = db.scalar(select(LedgerEvent).where(LedgerEvent.submission_id == submission_id))
    if existing:
        return existing
    candidates, issues = invoice_candidates(submission.snapshot)
    event = LedgerEvent(
        workspace_id=submission.workspace_id,
        submission_id=submission_id,
        month=submission.dispatched_at.astimezone(SHANGHAI).strftime("%Y-%m"),
        candidates=candidates,
        issues=issues,
        status="needs_attention" if issues else "audited",
    )
    db.add(event)
    db.flush()
    return event


def sync_event(db, event):
    gateway = db.scalar(select(GatewayResult).where(GatewayResult.submission_id == event.submission_id))
    if not gateway or gateway.status != "created":
        raise AppError("INVALID_STATE", "模拟审批已退回/撤销或缺少创建证据，不能投影台账", 409)
    # Caller locks this event. Only this local stub sink exists; audit remains the default.
    event.mode = "sync"
    issues = [x for x in event.issues if x.get("code") != "DUPLICATE_PROJECTION"]
    for candidate in event.candidates:
        duplicate = db.scalar(
            select(LedgerEntry).where(
                LedgerEntry.workspace_id == event.workspace_id,
                LedgerEntry.fingerprint == candidate["fingerprint"],
                LedgerEntry.status != "rolled_back",
            )
        )
        if duplicate:
            if duplicate.event_id != event.id:
                issues.append({"material_id": candidate["material_id"], "code": "DUPLICATE_PROJECTION"})
            continue
        values = deepcopy(candidate["values"])
        db.add(
            LedgerEntry(
                workspace_id=event.workspace_id,
                event_id=event.id,
                fingerprint=candidate["fingerprint"],
                values=values,
                original_values=deepcopy(values),
            )
        )
        db.flush()
    event.issues = issues
    event.status = "needs_attention" if issues else "simulated_synced"


def rollback_entry(entry):
    if entry.status == "rolled_back":
        return
    if entry.values != entry.original_values:
        raise AppError("LEDGER_CONFLICT", "当前投影已被修改，不能覆盖人工内容", 409)
    if entry.values[11] or entry.values[12] not in ("", "否"):
        raise AppError("LEDGER_BOOKED", "已入账记录不能自动回滚", 409)
    entry.status = "rolled_back"
