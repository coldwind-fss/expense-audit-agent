import asyncio
from datetime import datetime
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from sqlalchemy import func, select

from reimbursement.db import SessionLocal
from reimbursement.fixtures import documents
from reimbursement.main import app
from reimbursement.models import (
    FeedbackInvitation,
    GatewayResult,
    LedgerEntry,
    LedgerEvent,
    Submission,
)
from reimbursement.rules import effective_payment, normalize_facts
from reimbursement.submission_service import SHANGHAI, business_time, release_time
from reimbursement.worker import claim_job, process_job, tick


def call(c, path, body=None, method="POST", key=None, status=200):
    response = c.request(
        method, "/api/v1" + path, json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )
    assert response.status_code == status, response.text
    return response.json()


def get(c, path):
    response = c.get("/api/v1" + path)
    assert response.status_code == 200, response.text
    return response.json()


def drain(kinds=None):
    if kinds and "agent" in kinds:
        kinds = ["prepare", *kinds]

    async def run():
        for _ in range(60):
            if not await tick(kinds):
                return
        raise AssertionError("Unexpected unbounded queue")

    asyncio.run(run())


def fresh(c, claim):
    return get(c, "/claims/" + claim["id"])


def upload(c, claim, sample_key, line_id=None):
    sample = documents()[sample_key]
    result = c.post(
        f"/api/v1/claims/{claim['id']}/materials",
        data={"kind": sample["kind"], **({"target_line_id": line_id} if line_id else {})},
        files={"file": (sample["name"] + ".png", sample["content"], "image/png")},
    )
    assert result.status_code == 201, result.text
    return result.json()


def ready_claim(c, workflow="daily", route_mode="self", subject_id=None):
    claim = call(
        c,
        "/claims",
        {
            "title": "合成业务验收",
            "workflow_key": workflow,
            "route_mode": route_mode,
            "subject_id": subject_id,
        },
        status=201,
    )
    approvals = get(c, "/related-approvals?employee_id=" + claim["subject_id"])["items"]
    claim = call(
        c,
        "/claims/" + claim["id"],
        {
            "expected_revision": claim["revision"],
            "total_amount": "141.00" if workflow == "travel" else "88.00",
        },
        method="PATCH",
    )
    values = {"expected_revision": claim["revision"], "reason": "客户沟通工作餐", "project": "日常运营"}
    if workflow == "travel":
        values.update(
            reason="出差交通费",
            expense_type="差旅",
            related_id=next(a["id"] for a in approvals if a["approval_type"] == "travel"),
        )
    claim = call(c, f"/claims/{claim['id']}/lines", values, status=201)
    line_id = claim["lines"][0]["id"]
    keys = ["payment_refund", "rail_ticket"] if workflow == "travel" else ["payment_meal", "invoice_meal"]
    if workflow == "no_invoice":
        keys = ["payment_meal"]
    if workflow == "supply_chain":
        keys = ["invoice_meal"]
    for key in keys:
        upload(c, claim, key, line_id)
    drain(["agent"])
    claim = fresh(c, claim)
    run = call(c, f"/claims/{claim['id']}/suggestions", {"expected_revision": claim["revision"]}, status=202)
    drain(["agent"])
    run = get(c, "/agent-runs/" + run["run_id"])
    assert run["status"] == "completed", run
    batch = get(c, "/suggestion-batches/" + run["output"]["batch_id"])
    claim = call(
        c,
        "/suggestion-batches/" + batch["id"] + "/apply",
        {"expected_revision": claim["revision"], "selected_indices": list(range(len(batch["items"])))},
    )
    account = call(
        c, "/recipient-accounts", {"label": "合成工资卡", "value": "SYNTHETIC-ACCOUNT-0001"}, status=201
    )
    claim = call(
        c,
        "/claims/" + claim["id"],
        {"expected_revision": claim["revision"], "account_id": account["id"]},
        method="PATCH",
    )
    return claim


def review(c, claim):
    run = call(c, f"/claims/{claim['id']}/reviews", {"expected_revision": claim["revision"]}, status=202)
    drain(["agent"])
    run = get(c, "/agent-runs/" + run["run_id"])
    assert run["status"] == "completed", run
    return get(c, "/review-reports/" + run["output"]["report_id"])


@pytest.mark.parametrize("workflow", ["daily", "no_invoice", "travel", "project", "supply_chain"])
def test_five_workflows_full_submission_and_ledger(client, workflow):
    if workflow == "supply_chain":
        call(client, "/experience/persona", {"persona": "admin"})
    claim = ready_claim(client, workflow)
    if workflow == "travel":
        # 154 paid minus 10.50 refund supports 143.50, invoice supports 141; underclaim is valid.
        claim = call(
            client,
            f"/claims/{claim['id']}/lines/{claim['lines'][0]['id']}",
            {"expected_revision": claim["revision"], "amount": "141.00"},
            method="PATCH",
        )
    report = review(client, claim)
    assert report["can_submit"], [c for c in report["checks"] if c["blocks_submission"]]
    body = {"expected_revision": claim["revision"], "review_id": report["id"]}
    submission = call(client, f"/claims/{claim['id']}/submissions", body, status=202, key="submit-once")
    assert (
        call(client, f"/claims/{claim['id']}/submissions", body, status=202, key="submit-once")["id"]
        == submission["id"]
    )
    assert call(client, f"/claims/{claim['id']}/submissions", body, status=202)["id"] == submission["id"]
    drain(["dispatch", "ledger"])
    result = get(client, "/submissions/" + submission["id"])
    assert result["status"] == "succeeded" and result["simulated_reference"].startswith("SIM-")
    assert result["external_instance_id"] is None
    assert result["snapshot"]["base_revision"] == claim["revision"]
    call(
        client,
        "/claims/" + claim["id"],
        {"expected_revision": claim["revision"], "title": "不能修改锁定单据"},
        method="PATCH",
        status=409,
    )
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(GatewayResult)
                .where(GatewayResult.submission_id == submission["id"])
            )
            == 1
        )
        event = db.scalar(select(LedgerEvent).where(LedgerEvent.submission_id == submission["id"]))
        assert event and event.mode == "audit"
        assert len(event.candidates) == (0 if workflow == "no_invoice" else 1)
        assert not db.scalar(select(LedgerEntry).where(LedgerEntry.event_id == event.id))


def test_identity_isolation_money_and_stale_edits(client):
    me = get(client, "/me")
    people = get(client, "/employees")["items"]
    other = next(p for p in people if p["id"] != me["actor"]["id"])
    claim = call(client, "/claims", {"route_mode": "on_behalf", "subject_id": other["id"]}, status=201)
    assert claim["subject_id"] == other["id"] and claim["originator_id"] == me["actor"]["id"]
    call(client, "/claims", {"workflow_key": "supply_chain"}, status=403)
    call(client, "/claims", {"route_mode": "admin_originator"}, status=403)
    call(client, f"/claims/{claim['id']}/lines", {"expected_revision": 1, "amount": 2.02}, status=422)
    claim = call(
        client, f"/claims/{claim['id']}/lines", {"expected_revision": 1, "amount": "2.02"}, status=201
    )
    call(
        client,
        "/claims/" + claim["id"],
        {"expected_revision": 1, "title": "旧窗口"},
        method="PATCH",
        status=409,
    )
    with TestClient(app) as stranger:
        other_me = call(stranger, "/experience/sessions", status=201)
        stranger.headers["X-CSRF-Token"] = other_me["csrf_token"]
        assert stranger.get("/api/v1/claims/" + claim["id"]).status_code == 404
    client.headers.pop("X-CSRF-Token")
    assert (
        client.patch(
            "/api/v1/claims/" + claim["id"], json={"expected_revision": claim["revision"], "title": "伪造"}
        ).status_code
        == 403
    )


def test_manual_protection_report_invalidation_and_title_recheck(client):
    claim = ready_claim(client)
    report = review(client, claim)
    line = claim["lines"][0]
    claim = call(
        client,
        f"/claims/{claim['id']}/lines/{line['id']}",
        {"expected_revision": claim["revision"], "amount": "87.00", "business_date": "2026-01-01"},
        method="PATCH",
    )
    assert not get(client, "/review-reports/" + report["id"])["valid"]
    call(
        client,
        f"/claims/{claim['id']}/submissions",
        {"expected_revision": claim["revision"], "review_id": report["id"]},
        status=409,
    )
    run = call(
        client, f"/claims/{claim['id']}/suggestions", {"expected_revision": claim["revision"]}, status=202
    )
    drain(["agent"])
    batch = get(
        client, "/suggestion-batches/" + get(client, "/agent-runs/" + run["run_id"])["output"]["batch_id"]
    )
    indices = list(range(len(batch["items"])))
    assert any(i["protected"] for i in batch["items"])
    call(
        client,
        "/suggestion-batches/" + batch["id"] + "/apply",
        {"expected_revision": claim["revision"], "selected_indices": indices},
        status=409,
    )
    claim = call(
        client,
        "/suggestion-batches/" + batch["id"] + "/apply",
        {"expected_revision": claim["revision"], "selected_indices": indices, "replace_manual": True},
    )
    claim = call(
        client, "/suggestion-batches/" + batch["id"] + "/undo", {"expected_revision": claim["revision"]}
    )
    assert claim["lines"][0]["amount"] == "87.00" and claim["lines"][0]["business_date"] == "2026-01-01"
    # Wrong-company invoice has to be checked individually, even with sufficient aggregate support.
    upload(client, claim, "invoice_wrong_company", line["id"])
    drain(["agent"])
    claim = fresh(client, claim)
    report = review(client, claim)
    assert not report["can_submit"] and any(
        x["label"] == "发票抬头" and x["status"] == "fail" for x in report["checks"]
    )
    company = next(x for x in get(client, "/catalogs")["companies"] if x["name"] == "青禾供应链有限公司")
    claim = call(
        client,
        "/claims/" + claim["id"],
        {"expected_revision": claim["revision"], "company_id": company["id"]},
        method="PATCH",
    )
    assert not review(client, claim)["can_submit"]  # Original company-A invoice still mismatches.


def test_interrupt_unknown_material_and_fenced_results(client):
    claim = call(client, "/claims", {"workflow_key": "no_invoice"}, status=201)
    claim = call(
        client,
        f"/claims/{claim['id']}/lines",
        {
            "expected_revision": 1,
            "reason": "办公临时支出",
            "project": "日常运营",
            "business_date": "2026-11-06",
            "amount": "98.00",
        },
        status=201,
    )
    upload(client, claim, "transfer_ambiguous", claim["lines"][0]["id"])
    drain(["agent"])
    claim = fresh(client, claim)
    run = call(client, f"/claims/{claim['id']}/reviews", {"expected_revision": claim["revision"]}, status=202)
    drain(["agent"])
    waiting = get(client, "/agent-runs/" + run["run_id"])
    assert waiting["status"] == "waiting_input" and waiting["question"]["kind"] == "manual_amount"
    response = {
        "expected_revision": claim["revision"],
        "question_id": waiting["question"]["question_id"],
        "manual_amount": "98.00",
    }
    next_run = call(
        client, "/agent-runs/" + run["run_id"] + "/responses", response, key="response-once", status=202
    )
    assert (
        call(client, "/agent-runs/" + run["run_id"] + "/responses", response, key="response-once", status=202)
        == next_run
    )
    drain(["agent"])
    assert fresh(client, claim)["materials"][0]["manual_amount"] == "98.00"
    # Unregistered bytes named as a valid payment never acquire invented facts.
    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (80, 80), "pink").save(image, "PNG")
    result = client.post(
        f"/api/v1/claims/{claim['id']}/materials",
        data={"kind": "payment"},
        files={"file": ("已付88元.png", image.getvalue(), "image/png")},
    )
    assert result.status_code == 201
    drain(["agent"])
    assert get(client, "/materials/" + result.json()["id"])["status"] == "failed"
    claim = fresh(client, claim)
    queued = call(
        client, f"/claims/{claim['id']}/reviews", {"expected_revision": claim["revision"]}, status=202
    )
    claimed = claim_job(["agent"])
    assert claimed
    claim = call(
        client,
        "/claims/" + claim["id"],
        {"expected_revision": claim["revision"], "remark": "执行期间修改"},
        method="PATCH",
    )
    asyncio.run(process_job(*claimed))
    assert get(client, "/agent-runs/" + queued["run_id"])["status"] == "outdated"


@pytest.mark.parametrize(
    "day,expected",
    [(1, "2026-11-21T09:00:00+08:00"), (20, "2026-11-21T09:00:00+08:00"), (26, "2026-12-21T09:00:00+08:00")],
)
def test_monthly_release(day, expected):
    assert release_time(datetime(2026, 11, day, 13, tzinfo=SHANGHAI), True).isoformat() == expected


def test_refund_duplicate_decimal_and_scheduling_edges():
    f = normalize_facts(documents()["payment_refund"]["facts"], "m")
    assert f["countable_amount"] == "143.50"
    pending = normalize_facts({**documents()["payment_refund"]["facts"], "refund_status": "pending"}, "m")
    assert pending["countable_amount"] == "154.00"
    unpaid = {
        "kind": "payment",
        "manual_amount": "120.00",
        "facts": normalize_facts(documents()["order_unpaid"]["facts"], "m"),
    }
    assert effective_payment(unpaid) == 0
    assert (
        effective_payment({"kind": "payment", "duplicate_of": "a", "duplicate_kind": "exact", "facts": f})
        == 0
    )
    assert release_time(datetime(2026, 12, 26, tzinfo=SHANGHAI), True).year == 2027
    for day in [21, 25]:
        moment = datetime(2026, 11, day, 3, tzinfo=SHANGHAI)
        assert release_time(moment, True) == moment
    assert business_time(datetime(2026, 11, 21, 18, tzinfo=SHANGHAI)).day == 22
    assert business_time(datetime(2026, 11, 21, 8, 59, tzinfo=SHANGHAI)).hour == 9


def test_unknown_sidecar_cancel_and_copy(client):
    claim = ready_claim(client)
    report = review(client, claim)
    sub = call(
        client,
        f"/claims/{claim['id']}/submissions",
        {"expected_revision": claim["revision"], "review_id": report["id"]},
        status=202,
    )
    with SessionLocal() as db:
        db.get(Submission, sub["id"]).fault = "after_timeout"
        db.commit()
    drain(["dispatch"])
    assert get(client, "/submissions/" + sub["id"])["status"] == "unknown"
    call(client, "/experience/persona", {"persona": "admin"})
    job = next(j for j in get(client, "/admin/jobs")["items"] if j["entity_id"] == sub["id"])
    result = call(
        client,
        "/admin/jobs/" + job["id"] + "/actions",
        {"expected_status": "unknown", "action": "query", "reason": "核对模拟创建证据"},
    )
    assert result["submission"]["status"] == "succeeded"
    drain(["ledger"])
    event = next(e for e in get(client, "/ledger/events")["items"] if e["submission_id"] == sub["id"])
    call(client, "/ledger/events/" + event["id"] + "/sync", {"reason": "核对本地台账投影"})
    call(client, "/ledger/events/" + event["id"] + "/sync", {"reason": "重复同步验证幂等"})
    entries = [e for e in get(client, "/ledger/entries")["items"] if e["event_id"] == event["id"]]
    assert len(entries) == 1 and len(entries[0]["values"]) == 13
    with SessionLocal() as db:
        entry = db.get(LedgerEntry, entries[0]["id"])
        entry.values = [*entry.values[:12], "是"]
        db.commit()
    call(
        client, "/ledger/entries/" + entries[0]["id"] + "/rollback", {"reason": "已入账不可回滚"}, status=409
    )
    with SessionLocal() as db:
        entry = db.get(LedgerEntry, entries[0]["id"])
        entry.values = list(entry.original_values)
        db.commit()
    call(client, "/ledger/entries/" + entries[0]["id"] + "/rollback", {"reason": "回滚未入账模拟行"})


def test_admin_case_and_feedback_roundtrip(client):
    assert client.get("/api/v1/admin/jobs").status_code == 403
    call(client, "/experience/persona", {"persona": "admin"})
    people = get(client, "/employees")["items"]
    subject = people[0]
    case = call(
        client,
        "/admin/cases/manual",
        {"subject_id": subject["id"], "reason": "协助员工补齐报销"},
        status=201,
        key="manual-case",
    )
    detail = get(client, "/admin/cases/" + case["id"])
    assert detail["claim"]["originator_id"] == subject["id"] and detail["claim"]["status"] == "draft"
    with SessionLocal() as db:
        assert not db.scalar(select(Submission).where(Submission.claim_id == detail["claim_id"]))
    result = call(
        client,
        "/feedback/invitations",
        {"campaign": "验收批次", "employee_ids": [subject["id"], subject["id"]]},
        status=201,
    )
    assert len(result["items"]) == 1
    token = result["items"][0]["url"].split("token=")[1]
    assert call(
        client, "/feedback/invitations", {"campaign": "验收批次", "employee_ids": [subject["id"]]}, status=201
    )["items"][0]["deduplicated"]
    with TestClient(app) as respondent:
        resolved = call(respondent, "/feedback/resolve", {"token": token})
        assert not resolved["submitted"]
        body = {
            "token": token,
            "difficulty": "recognition",
            "priority": "validation",
            "suggestion": "希望问题提示更清楚",
        }
        answer = call(respondent, "/feedback/answers", body, status=201)
        assert call(respondent, "/feedback/answers", body, status=201)["id"] == answer["id"]
        call(respondent, "/feedback/answers", {**body, "priority": "invented"}, status=422)
    assert get(client, "/feedback/invitations")["items"][0]["status"] == "submitted"
    with SessionLocal() as db:
        invitation = db.get(FeedbackInvitation, result["items"][0]["id"])
        assert token != invitation.token_hash
    failed = call(
        client, "/feedback/invitations", {"campaign": "重试批次", "employee_ids": [subject["id"]]}, status=201
    )["items"][0]
    old_token = failed["url"].split("token=")[1]
    with SessionLocal() as db:
        db.get_one(FeedbackInvitation, failed["id"]).status = "failed"
        db.commit()
    retried = call(
        client, "/feedback/invitations/" + failed["id"] + "/retry", {"reason": "重试明确失败的邀请"}
    )
    assert retried["id"] == failed["id"]
    call(client, "/feedback/resolve", {"token": old_token}, status=404)
    assert (
        call(client, "/feedback/resolve", {"token": retried["url"].split("token=")[1]})["submitted"] is False
    )


def test_excel_import_job_with_embedded_materials(client):
    claim = call(client, "/claims", {}, status=201)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["申请事由", "金额", "付款截图", "发票", "费用日期", "所属项目"])
    sheet.append(["办公用品采购", "88.00", None, None, "2026-11-06", "日常运营"])
    sheet.append(["缺材料行", "10.00"])
    for key, cell in [("payment_meal", "C2"), ("invoice_meal", "D2")]:
        image = ExcelImage(BytesIO(documents()[key]["content"]))
        sheet.add_image(image, cell)
    content = BytesIO()
    workbook.save(content)
    r = client.post(
        f"/api/v1/claims/{claim['id']}/imports",
        data={"expected_revision": 1},
        files={
            "file": (
                "费用.xlsx",
                content.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 202, r.text
    drain(["import"])
    job = get(client, "/import-jobs/" + r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["imported"] == 1 and job["result"]["items"][1]["status"] == "skipped"
    drain(["agent"])
    claim = fresh(client, claim)
    assert claim["lines"][0]["sources"]["amount"]["kind"] == "import"
    assert claim["total_amount"] is None and claim["total_auto"] is False
