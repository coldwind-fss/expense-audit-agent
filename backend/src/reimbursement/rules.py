"""Financial and workflow rules are deterministic. Material interpretation is an Agent task."""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Claim, ClaimLine, Material

TOLERANCE = Decimal("0.01")
ZERO = Decimal("0")
INVOICE_ROLES = {"tax_invoice", "title_exempt_transport_receipt"}
POLICY_VERSION = "reimbursement-v1-002"


def decimal(value) -> Decimal:
    return Decimal(str(value or "0"))


def amount(value) -> str:
    return format(decimal(value), ".2f")


def normalize_facts(raw: dict, material_id: str, *, execution_mode="fixture") -> dict:
    facts = {**raw}
    role = facts.get("document_role", "unknown")
    countable = ZERO
    decision = "manual"
    if role in INVOICE_ROLES:
        countable, decision = decimal(facts.get("amount")), "included"
    elif role == "supporting_document":
        decision = "excluded"
    elif role == "payment":
        if facts.get("payment_status") == "paid":
            transactions = facts.get("transactions") or []
            if transactions:
                unique = {t["id"]: decimal(t["amount"]) for t in transactions if t.get("id")}
                countable = sum(unique.values(), ZERO)
            else:
                countable = decimal(facts.get("amount"))
            if facts.get("refund_amount"):
                refund_status = facts.get("refund_status")
                if refund_status in {None, "unknown"} and any(
                    x.get("type") == "refunded" for x in facts.get("observations", [])
                ):
                    refund_status = "completed"
                if refund_status == "pending":
                    pass
                elif refund_status == "completed" and facts.get("refund_linked"):
                    countable -= decimal(facts["refund_amount"])
                else:
                    decision = "manual"
                    countable = ZERO
            if countable > ZERO:
                decision = "included"
        elif facts.get("payment_status") == "unpaid":
            decision = "excluded"
    facts.update(
        countable_amount=amount(max(ZERO, countable)),
        decision=decision,
        evidence_refs=[{"material_id": material_id, "page": 1, "field": "document_content"}],
        schema_version="material.v1",
        prompt_version="material_extract.v1",
        execution_mode=execution_mode,
    )
    return facts


def effective_payment(material: dict) -> Decimal:
    if material.get("duplicate_of") and (
        material.get("duplicate_kind") == "exact" or material.get("duplicate_decision") != "different"
    ):
        return ZERO
    facts = material.get("facts", {})
    role = facts.get("document_role")
    if material.get("kind") != "payment":
        return ZERO
    if facts.get("payment_status") == "unpaid":
        return ZERO
    if material.get("manual_amount") is not None and role in {"payment", "unknown"}:
        return decimal(material["manual_amount"])
    if role != "payment" or facts.get("decision") != "included":
        return ZERO
    return decimal(facts.get("countable_amount"))


def effective_invoice(material: dict) -> Decimal:
    if material.get("duplicate_of") and (
        material.get("duplicate_kind") == "exact" or material.get("duplicate_decision") != "different"
    ):
        return ZERO
    facts = material.get("facts", {})
    if material.get("kind") != "invoice" or facts.get("document_role") not in INVOICE_ROLES:
        return ZERO
    return decimal(facts.get("countable_amount")) if facts.get("decision") == "included" else ZERO


def sync_line_amounts(db: Session, claim: Claim):
    from .services import material_view

    db.flush()
    materials = [
        material_view(m)
        for m in db.scalars(
            select(Material).where(Material.claim_id == claim.id, Material.status != "deleted")
        )
    ]
    for line in db.scalars(select(ClaimLine).where(ClaimLine.claim_id == claim.id)):
        source = line.sources.get("amount", {})
        if line.amount is not None and source.get("kind") in {"manual", "import"}:
            continue
        row_materials = [m for m in materials if m["line_id"] == line.id]
        total = sum(
            (
                effective_invoice(m) if claim.workflow_key == "supply_chain" else effective_payment(m)
                for m in row_materials
            ),
            ZERO,
        )
        line.amount = total if total > ZERO else None
        line.sources = {
            **line.sources,
            "amount": {"kind": "system", "evidence": [m["id"] for m in row_materials]},
        }


def company_name(value: str) -> str:
    value = re.sub(r"^(?:公司全称|购买方名称|购买方|名称)[：: ]*", "", value)
    return re.sub(r"[\s，,。·：:]", "", value)


def evaluate(snapshot: dict) -> dict:
    claim, materials = snapshot["claim"], snapshot["claim"]["materials"]
    checks: list[dict] = []
    workflow = claim["workflow_key"]
    if workflow == "no_invoice":
        forbidden = [m for m in materials if m["kind"] == "invoice"]
        if forbidden:
            checks.append(
                {
                    "check_id": "R-11:no_invoice",
                    "rule_id": "R-11",
                    "scope": "claim",
                    "label": "有票/无票分流",
                    "status": "fail",
                    "severity": "error",
                    "message": "无票入口不接收发票材料，请按实际情况使用有票入口或移除误传发票",
                    "evidence_refs": [m["id"] for m in forbidden],
                    "next_action": "核对入口与发票材料",
                    "blocks_submission": True,
                }
            )
    companies = {x["id"]: x["name"] for x in snapshot.get("companies", [])}
    approvals = {x["id"]: x for x in snapshot.get("approvals", [])}
    total = ZERO

    def check(rule, scope, label, status, message, refs=None, action="", severity="error", blocks=None):
        failed = status == "fail" or (status == "unknown" and blocks is True)
        checks.append(
            {
                "check_id": f"{rule}:{scope}:{len(checks)}",
                "rule_id": rule,
                "scope": scope,
                "label": label,
                "status": status,
                "severity": severity,
                "message": message,
                "evidence_refs": refs or [],
                "next_action": action,
                "blocks_submission": failed and severity == "error",
            }
        )

    check(
        "R-12",
        "claim",
        "费用明细",
        "pass" if claim["lines"] else "fail",
        "已建立费用明细" if claim["lines"] else "请至少建立一条费用明细",
        action="填写明细",
    )
    check(
        "R-13",
        "claim",
        "付款公司",
        "pass" if claim.get("company_id") in companies else "fail",
        "付款公司已确认" if claim.get("company_id") in companies else "请选择有效付款公司",
        action="确认公司和账户",
    )
    check(
        "R-12",
        "claim",
        "收款账户",
        "pass" if snapshot.get("account_valid") else "fail",
        "已选择收款账户" if snapshot.get("account_valid") else "请选择有效收款账户",
        action="确认公司和账户",
    )
    if claim.get("social_company_id") and claim.get("company_id") != claim["social_company_id"]:
        check(
            "R-13",
            "claim",
            "社保主体提示",
            "pass",
            "本次付款公司与社保主体不同，已保留您的选择",
            severity="warning",
        )
    selected = [approvals[x] for x in claim.get("related_ids", []) if x in approvals]
    unassigned = [m for m in materials if m["kind"] in {"payment", "invoice"} and not m["line_id"]]
    check(
        "R-01",
        "claim",
        "附件归属",
        "fail" if unassigned else "pass",
        f"还有{len(unassigned)}份材料未分配" if unassigned else "待核验材料均有归属",
        [m["id"] for m in unassigned],
        "分配附件",
    )
    not_ready = [m for m in materials if m["kind"] != "other" and m["status"] != "recognized"]
    if snapshot.get("execution_mode") == "provider":
        wrong_mode = [
            m for m in materials if m["kind"] != "other" and m["facts"].get("execution_mode") != "provider"
        ]
        check(
            "R-01",
            "claim",
            "真实模型证据来源",
            "fail" if wrong_mode else "pass",
            "材料事实来自真实模型" if not wrong_mode else "存在非真实模型事实，请重新识别",
            [m["id"] for m in wrong_mode],
            "重新识别材料",
        )
    check(
        "R-01",
        "claim",
        "材料识别",
        "fail" if not_ready else "pass",
        "部分材料尚未识别，请处理失败项或等待完成" if not_ready else "相关材料已完成识别",
        [m["id"] for m in not_ready],
        "查看材料识别结果",
    )
    for m in materials:
        if m.get("duplicate_of"):
            confirmed = m.get("duplicate_kind") == "exact" or m.get("duplicate_decision") in {
                "same",
                "different",
            }
            check(
                "R-05",
                m["id"],
                "凭证去重",
                "pass" if confirmed else "fail",
                "重复凭证已排除/确认" if confirmed else "疑似重复，请核对同一份还是不同凭证",
                [m["id"]],
                "核对重复凭证",
            )
    for line in claim["lines"]:
        scope = line["id"]
        label = line["reason"] or "未填写事由的费用"
        declared = decimal(line.get("amount"))
        total += declared
        required = [
            bool(line.get("business_date")),
            bool(line.get("reason", "").strip()),
            declared > ZERO,
            bool(line.get("expense_type")) if workflow == "travel" else bool(line.get("project")),
        ]
        if workflow != "no_invoice":
            required.append(bool(line.get("invoice_type")))
        check(
            "R-12",
            scope,
            "明细完整性",
            "pass" if all(required) else "fail",
            f"{label}：必要信息完整"
            if all(required)
            else f"{label}：请补费用日期、事由、正数金额及项目/类型、票种",
            action="填写明细",
        )
        row_materials = [m for m in materials if m["line_id"] == scope]
        payments = [m for m in row_materials if m["kind"] == "payment"]
        invoices = [m for m in row_materials if m["kind"] == "invoice"]
        paid = sum((effective_payment(m) for m in payments), ZERO)
        invoiced = sum((effective_invoice(m) for m in invoices), ZERO)
        if workflow != "supply_chain":
            supported = bool(payments) and paid > ZERO and declared - paid <= TOLERANCE
            check(
                "R-07",
                scope,
                "付款支持",
                "pass" if supported else "fail",
                f"付款支持 {amount(paid)} 元，申报 {amount(declared)} 元"
                + ("" if supported else "，请补充/核对付款凭证"),
                [m["id"] for m in payments],
                "补充或核对付款凭证",
            )
            if paid - declared > TOLERANCE:
                check(
                    "R-07",
                    scope,
                    "少报提示",
                    "pass",
                    f"付款高于申报 {amount(paid - declared)} 元，只按申报金额报销",
                    severity="warning",
                )
        requires_invoice = workflow != "no_invoice"
        if requires_invoice:
            supported = bool(invoices) and invoiced > ZERO and declared - invoiced <= TOLERANCE
            if workflow == "supply_chain":
                supported = (
                    any(m["facts"].get("document_role") == "tax_invoice" for m in invoices)
                    and abs(declared - invoiced) <= TOLERANCE
                )
            check(
                "R-09" if workflow == "supply_chain" else "R-08",
                scope,
                "票据支持",
                "pass" if supported else "fail",
                f"有效票据 {amount(invoiced)} 元，申报 {amount(declared)} 元"
                + ("" if supported else "，佐证不能代替发票"),
                [m["id"] for m in invoices],
                "补充有效票据",
            )
            if line.get("invoice_type") == "无":
                check(
                    "R-11",
                    scope,
                    "有票/无票分流",
                    "fail",
                    "当前为有票入口，无票费用请使用独立无票入口",
                    action="核对报销入口",
                )
            for material in invoices:
                facts = material["facts"]
                if facts.get("document_role") == "tax_invoice":
                    matched = company_name(facts.get("buyer_name", "")) == company_name(
                        companies.get(claim.get("company_id"), "")
                    ) and bool(facts.get("buyer_name"))
                    check(
                        "R-14",
                        scope,
                        "发票抬头",
                        "pass" if matched else "fail",
                        "购买方与所选公司一致"
                        if matched
                        else f"发票购买方“{facts.get('buyer_name') or '未识别'}”与所选公司不一致",
                        [material["id"]],
                        "补票或核对付款公司",
                    )
        relation_type = None
        text = line["reason"] + " " + line.get("remark", "")
        if workflow != "project":
            if re.search("团建|部门活动", text):
                relation_type = "team"
            elif re.search("出差|高铁|火车|机票|住宿|酒店", text):
                relation_type = "travel"
            elif re.search("打车|出租车|网约车|滴滴|高德", text):
                relation_type = "taxi"
        if workflow == "travel":
            relation_type = "travel"
        if relation_type:
            candidates = (
                [approvals[line["related_id"]]]
                if line.get("related_id") in approvals
                else (selected if workflow != "travel" else [])
            )
            valid = [
                a
                for a in candidates
                if a["employee_id"] == claim["subject_id"]
                and (
                    a["approval_type"] in {"travel", "outing"}
                    if relation_type == "taxi"
                    else a["approval_type"] == relation_type
                )
            ]
            check(
                "R-16",
                scope,
                "前置业务审批",
                "pass" if valid else "fail",
                "已明确关联对应审批"
                if valid
                else f"{label}需关联"
                + {"team": "部门活动特别审批", "travel": "出差审批", "taxi": "外出或出差审批"}[relation_type],
                action="选择关联审批",
            )
            if valid and any(a["status"] != "approved" for a in valid):
                check(
                    "R-17",
                    scope,
                    "审批状态政策",
                    "unknown",
                    "该审批状态不在已确定样本政策内，需要确认",
                    action="联系业务负责人确认",
                    blocks=True,
                )
        if workflow == "travel" and line.get("business_date") and line.get("related_id") in approvals:
            approval = approvals[line["related_id"]]
            expense_date = date.fromisoformat(line["business_date"])
            start, end = date.fromisoformat(approval["start_date"]), date.fromisoformat(approval["end_date"])
            actual_dates = [
                date.fromisoformat(m["facts"]["business_date"])
                for m in row_materials
                if m["facts"].get("date_type") in {"ride", "flight", "stay", "transaction"}
                and m["facts"].get("business_date")
            ]
            conflict = not start <= expense_date <= end or any(
                not start <= d <= end or d != expense_date for d in actual_dates
            )
            explanation = claim.get("travel_date_remark", "").strip()
            if conflict:
                explained = len(re.sub(r"\s", "", explanation)) >= 4
                check(
                    "R-20",
                    scope,
                    "差旅日期说明",
                    "pass" if explained else "fail",
                    "日期冲突已保留人工说明" if explained else "日期存在冲突，请填写4—500字符的真实说明",
                    action="填写日期说明",
                    severity="warning" if explained else "error",
                )
            else:
                check(
                    "R-19",
                    scope,
                    "差旅日期",
                    "pass" if actual_dates else "unknown",
                    "费用及实际日期位于出差范围"
                    if actual_dates
                    else "费用日期在范围内；未取得可靠票据实际日期，按原规则提示继续",
                    severity="info" if actual_dates else "warning",
                    blocks=False,
                )
    declared_total = decimal(claim.get("total_amount"))
    independent_total = declared_total > ZERO and not claim.get("total_auto", False)
    check(
        "R-09",
        "claim",
        "人工申报总金额",
        "pass" if independent_total else "fail",
        f"已独立填写申报总金额 {amount(declared_total)} 元"
        if independent_total
        else "请在基本信息中独立填写本次申报总金额，不能使用自动汇总值代替",
        action="前往基本信息填写申报总金额",
    )
    check(
        "R-09",
        "claim",
        "整单金额",
        "pass" if independent_total and abs(declared_total - total) <= TOLERANCE else "fail",
        f"人工申报 {amount(declared_total)} 元 / 明细合计 {amount(total)} 元"
        + (f" / 差额 {amount(declared_total - total)} 元" if independent_total else "；人工申报总金额待填写"),
        action="核对总金额",
    )
    blockers = [c for c in checks if c["blocks_submission"]]
    return {
        "checks": checks,
        "can_submit": not blockers,
        "summary": {
            "declared_amount": amount(declared_total),
            "line_total": amount(total),
            "checked": len(checks),
            "blocking": len(blockers),
            "warnings": sum(c["severity"] == "warning" for c in checks),
            "policy_version": POLICY_VERSION,
        },
    }
