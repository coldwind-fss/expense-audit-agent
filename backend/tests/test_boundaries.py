import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from test_workflows import call, drain, fresh, get, ready_claim, review, upload

from reimbursement.agent_graph import make_tools
from reimbursement.agent_service import publish, review_snapshot, worker_context
from reimbursement.db import SessionLocal, now
from reimbursement.errors import AppError
from reimbursement.ledger import invoice_candidates
from reimbursement.models import AgentRun, Claim, GatewayResult, Job, LedgerEvent, Submission
from reimbursement.rules import evaluate
from reimbursement.submission_service import SHANGHAI, dispatch
from reimbursement.worker import claim_job, process_job


def snapshot(claim):
    with SessionLocal() as db:
        row = db.get_one(Claim, claim["id"])
        return review_snapshot(db, worker_context(db, row.workspace_id, row.actor_id), row)


@pytest.mark.parametrize(
    "value,allowed", [("87.00", True), ("88.00", True), ("88.01", True), ("88.02", False)]
)
def test_money_tolerance_is_one_cent(client, value, allowed):
    claim = ready_claim(client)
    data = snapshot(claim)
    data["claim"]["lines"][0]["amount"] = value
    data["claim"]["total_amount"] = value
    assert evaluate(data)["can_submit"] is allowed


def test_independent_total_survives_recognition_and_blocks_mismatch(client):
    draft = call(client, "/claims", {"title": "独立人工总额"}, status=201)
    assert draft["total_amount"] is None and draft["total_auto"] is False
    call(
        client,
        "/claims/" + draft["id"],
        {
            "expected_revision": draft["revision"],
            "total_auto": True,
        },
        method="PATCH",
        status=422,
    )
    claim = ready_claim(client)
    claim = call(
        client,
        "/claims/" + claim["id"],
        {
            "expected_revision": claim["revision"],
            "total_amount": "100.00",
        },
        method="PATCH",
    )
    # Reassign recognized evidence: line synchronization must never replace the human total.
    material = claim["materials"][0]
    line_id = material["line_id"]
    for target in [None, line_id]:
        claim = call(
            client,
            f"/claims/{claim['id']}/bindings",
            {
                "expected_revision": claim["revision"],
                "bindings": [{"material_id": material["id"], "line_id": target, "kind": material["kind"]}],
            },
            method="PUT",
        )
    assert claim["total_amount"] == "100.00" and claim["lines"][0]["amount"] == "88.00"
    report = review(client, claim)
    assert not report["can_submit"]
    assert report["summary"]["declared_amount"] == "100.00"
    assert report["summary"]["line_total"] == "88.00"
    assert any(x["label"] == "整单金额" and x["status"] == "fail" for x in report["checks"])
    call(
        client,
        f"/claims/{claim['id']}/submissions",
        {
            "expected_revision": claim["revision"],
            "review_id": report["id"],
        },
        status=422,
    )
    for missing in [None, "0.00"]:
        data = snapshot(claim)
        data["claim"]["total_amount"] = missing
        assert not evaluate(data)["can_submit"]
    data = snapshot(claim)
    data["claim"].update(total_auto=True, total_amount="88.00")
    assert not evaluate(data)["can_submit"]
    claim = call(
        client,
        "/claims/" + claim["id"],
        {
            "expected_revision": claim["revision"],
            "total_amount": "88.00",
        },
        method="PATCH",
    )
    assert not get(client, "/review-reports/" + report["id"])["valid"]
    assert review(client, claim)["can_submit"]


def test_date_ranges_roles_and_association_scope(client):
    claim = ready_claim(client, "travel")
    data = snapshot(claim)
    data["claim"]["lines"][0]["amount"] = "141.00"
    data["claim"]["total_amount"] = "141.00"
    line = data["claim"]["lines"][0]
    approval = data["approvals"][0]
    line["business_date"] = approval["start_date"]
    for material in data["claim"]["materials"]:
        material["facts"]["business_date"] = approval["start_date"]
    assert evaluate(data)["can_submit"]
    # Invoice issue dates are not actual journey dates.
    data["claim"]["materials"][1]["facts"].update(date_type="invoice_issue", business_date="2001-01-01")
    assert evaluate(data)["can_submit"]
    data["claim"]["materials"][0]["facts"].update(date_type="transaction", business_date="2001-01-01")
    assert not evaluate(data)["can_submit"]
    data["claim"]["travel_date_remark"] = "因预订行程提前支付"
    assert evaluate(data)["can_submit"]
    data["claim"]["travel_date_remark"] = ""
    for m in data["claim"]["materials"]:
        m["facts"]["date_type"] = "unknown"
    assert evaluate(data)["can_submit"]  # Expense is inside range; reliable actual dates unknown.
    line["related_id"] = None
    data["claim"]["related_ids"] = [approval["id"]]
    assert not evaluate(data)["can_submit"]  # Travel never falls back to the first global approval.
    line["related_id"] = approval["id"]
    approval["status"] = "unknown"
    assert not evaluate(data)["can_submit"]


def test_material_identity_movement_and_tool_scope(client):
    claim = ready_claim(client)
    first = claim["lines"][0]
    material = claim["materials"][0]
    same = upload(client, claim, "payment_meal")
    assert same["id"] == material["id"]
    renamed = call(client, "/materials/" + material["id"], {"name": "我重新命名的付款截图"}, method="PATCH")
    assert renamed["fact_version"] == material["fact_version"]
    claim = fresh(client, claim)
    copied = call(
        client, f"/claims/{claim['id']}/lines/{first['id']}/copy", {"expected_revision": claim["revision"]}
    )
    assert len(copied["lines"]) == 2
    second = next(x for x in copied["lines"] if x["id"] != first["id"])
    assert all(m["line_id"] != second["id"] for m in copied["materials"])
    copied = call(
        client,
        f"/claims/{claim['id']}/lines/{first['id']}?expected_revision={copied['revision']}",
        method="DELETE",
    )
    assert all(m["line_id"] is None for m in copied["materials"])
    tool = make_tools(snapshot(copied), "claim_review")["read_material_pages"]
    with pytest.raises(AppError, match="当前任务以外"):
        tool.invoke({"material_id": "foreign-material"})
    other_workspace = call(client, "/experience/persona", {"persona": "colleague"})
    assert other_workspace["actor"]["persona"] == "colleague"
    assert client.get("/api/v1/materials/" + material["id"] + "/preview?page=1").status_code == 404


def test_concurrent_claim_lease_restart_and_duplicate_publication(client):
    drain(["agent"])
    one = call(client, "/claims", {}, status=201)
    two = call(client, "/claims", {}, status=201)
    runs = [
        call(client, f"/claims/{c['id']}/reviews", {"expected_revision": c["revision"]}, status=202)
        for c in [one, two]
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: claim_job(["agent"]), range(2)))
    assert all(claimed) and claimed[0][0] != claimed[1][0]
    job_id, old_token = claimed[0]
    with SessionLocal() as db:
        job = db.get_one(Job, job_id)
        job.lease_until = now() - timedelta(seconds=1)
        run = db.get_one(AgentRun, job.entity_id)
        old_attempt, run.model_calls = run.attempt_id, 1
        db.commit()
    replacement = claim_job(["agent"])
    assert replacement[0] == job_id and replacement[1] != old_token
    asyncio.run(process_job(job_id, old_token))
    asyncio.run(process_job(*replacement))
    asyncio.run(process_job(*claimed[1]))
    with SessionLocal() as db:
        job = db.get_one(Job, job_id)
        run = db.get_one(AgentRun, job.entity_id)
        assert run.attempt_id != old_attempt and run.model_calls > 1 and run.status == "completed"
        result = dict(run.output)
        context = worker_context(db, run.workspace_id, run.snapshot["actor_id"])
        publish(db, context, run, job_id, replacement[1], {"review": {}})
        db.commit()
        assert run.output == result  # A completed job cannot publish a second report.
    assert all(get(client, "/agent-runs/" + r["run_id"])["status"] == "completed" for r in runs)


def test_cancel_copy_and_sidecar_failure_are_independent(client):
    claim = ready_claim(client)
    report = review(client, claim)
    sub = call(
        client,
        f"/claims/{claim['id']}/submissions",
        {"expected_revision": claim["revision"], "review_id": report["id"]},
        status=202,
    )
    new = call(
        client,
        f"/submissions/{sub['id']}/cancel-and-copy",
        {"expected_revision": claim["revision"], "expected_status": "scheduled"},
        status=201,
        key="copy-once",
    )
    assert new["id"] != claim["id"] and new["status"] == "draft"
    assert len(new["materials"]) == 2 and len(new["lines"]) == 1
    assert get(client, "/submissions/" + sub["id"])["status"] == "cancelled"
    report = review(client, new)
    sub2 = call(
        client,
        f"/claims/{new['id']}/submissions",
        {"expected_revision": new["revision"], "review_id": report["id"]},
        status=202,
    )
    with SessionLocal() as db:
        db.get_one(Submission, sub2["id"]).fault = "sidecar_failure"
        db.commit()
    drain(["dispatch", "ledger"])
    assert get(client, "/submissions/" + sub2["id"])["status"] == "succeeded"
    call(client, "/experience/persona", {"persona": "admin"})
    failed = next(
        j
        for j in get(client, "/admin/jobs")["items"]
        if j["entity_id"] == sub2["id"] and j["kind"] == "ledger"
    )
    assert failed["status"] == "failed"
    call(
        client,
        "/admin/jobs/" + failed["id"] + "/actions",
        {"action": "retry", "expected_status": "failed", "reason": "单独恢复台账旁路"},
    )
    drain(["ledger"])
    with SessionLocal() as db:
        assert (
            len(db.scalars(select(GatewayResult).where(GatewayResult.submission_id == sub2["id"])).all()) == 1
        )
        assert db.scalar(select(LedgerEvent).where(LedgerEvent.submission_id == sub2["id"]))


def test_persistent_dispatch_guard_limits_parallel_consumers(client):
    drain(["dispatch", "ledger"])
    submissions = []
    for _ in range(2):
        claim = ready_claim(client)
        report = review(client, claim)
        submissions.append(
            call(
                client,
                f"/claims/{claim['id']}/submissions",
                {"expected_revision": claim["revision"], "review_id": report["id"]},
                status=202,
            )
        )
    with SessionLocal() as db:
        for sub in submissions:
            job = db.scalars(select(Job).where(Job.kind == "dispatch", Job.entity_id == sub["id"])).one()
            job.payload = {**job.payload, "pooled": True}
        db.commit()
    first, second = claim_job(["dispatch"]), claim_job(["dispatch"])
    moment = datetime(2026, 11, 21, 9, tzinfo=SHANGHAI)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda args: dispatch(*args, moment=moment), [first, second]))
    with SessionLocal() as db:
        statuses = [db.get_one(Submission, s["id"]).status for s in submissions]
        assert statuses.count("succeeded") == 1
        queued = db.scalars(
            select(Job).where(
                Job.kind == "dispatch",
                Job.entity_id.in_([s["id"] for s in submissions]),
                Job.status == "queued",
            )
        ).one()
        assert queued.available_at == moment + timedelta(minutes=3)
        queued.available_at = now() - timedelta(seconds=1)
        db.commit()
    replacement = claim_job(["dispatch"])
    dispatch(*replacement, moment=moment + timedelta(minutes=3))
    assert all(get(client, "/submissions/" + s["id"])["status"] == "succeeded" for s in submissions)


def test_ledger_missing_fields_and_amount_tax_equation(client):
    claim = ready_claim(client)
    source = snapshot(claim)
    candidates, issues = invoice_candidates(source)
    assert len(candidates) == 1 and not issues
    assert candidates[0]["values"][8:11] == ["83.02", "4.98", "88.00"]
    broken = deepcopy(source)
    invoice = next(m for m in broken["claim"]["materials"] if m["kind"] == "invoice")
    invoice["facts"]["seller_name"] = ""
    assert invoice_candidates(broken)[1][0]["code"] == "MISSING_FIELDS"
    invoice["facts"]["seller_name"] = "合成商家"
    invoice["facts"]["tax_amount"] = "1.00"
    assert invoice_candidates(broken)[1][0]["code"] == "AMOUNT_TAX_MISMATCH"


@pytest.mark.parametrize("mode", ["budget", "no_progress", "invalid_structure", "disabled"])
def test_agent_failure_modes_stop_without_publishing_facts(client, monkeypatch, mode):
    from reimbursement import agent_graph
    from reimbursement.config import settings

    if mode == "disabled":
        monkeypatch.setattr(settings(), "model_mode", "disabled")
    claim = call(client, "/claims", {}, status=201)
    material = upload(client, claim, "payment_meal")
    drain(["prepare"])
    if mode == "budget":
        with SessionLocal() as db:
            run = db.scalars(select(AgentRun).where(AgentRun.material_id == material["id"])).one()
            run.model_calls = 4
            db.commit()
    elif mode == "no_progress":
        monkeypatch.setattr(
            agent_graph,
            "fixture_action",
            lambda state: {
                "action": "tool",
                "tool_name": "read_material_pages",
                "arguments": {"material_id": material["id"]},
            },
        )
    elif mode == "invalid_structure":
        monkeypatch.setattr(
            agent_graph,
            "fixture_action",
            lambda state: {"action": "finish", "facts": {"document_role": "payment", "amount": "NaN"}},
        )
    drain(["agent"])
    result = get(client, "/materials/" + material["id"])
    assert result["status"] == "failed" and result["fact_version"] == 0
    with SessionLocal() as db:
        run = db.scalars(select(AgentRun).where(AgentRun.material_id == material["id"])).one()
        assert run.status == "failed" and run.model_calls <= 4 and run.tool_calls <= 8


def test_pdf_preparation_and_upload_boundary(client):
    from io import BytesIO

    from PIL import Image

    claim = call(client, "/claims", {}, status=201)
    pdf = BytesIO()
    Image.new("RGB", (100, 150), "white").save(
        pdf, "PDF", save_all=True, append_images=[Image.new("RGB", (100, 150), "blue")]
    )
    result = client.post(
        f"/api/v1/claims/{claim['id']}/materials",
        data={"kind": "payment"},
        files={"file": ("两页.pdf", pdf.getvalue(), "application/pdf")},
    )
    assert result.status_code == 201
    drain(["prepare"])
    material = get(client, "/materials/" + result.json()["id"])
    assert material["page_count"] == 2 and material["status"] == "ready_for_extraction"
    assert client.get(f"/api/v1/materials/{material['id']}/preview?page=2").status_code == 200
    assert client.get(f"/api/v1/materials/{material['id']}/preview?page=3").status_code == 404
    bad = client.post(
        f"/api/v1/claims/{claim['id']}/materials",
        data={"kind": "payment"},
        files={"file": ("伪装图片.png", b"<script>alert(1)</script>", "image/png")},
    )
    assert bad.status_code == 415


def test_controlled_admin_repair_submission_and_simulated_rejection(client):
    from urllib.parse import quote

    claim = ready_claim(client)
    original_report = review(client, claim)
    approval = get(client, "/related-approvals")["items"][0]
    resolved = get(client, "/related-approvals/resolve?business_id=" + approval["business_id"])
    assert resolved["id"] == approval["id"]
    call(client, "/experience/persona", {"persona": "admin"})
    case = call(
        client, "/admin/cases", {"claim_id": claim["id"], "reason": "协助员工核对公司信息"}, status=201
    )
    call(
        client,
        "/claims/" + claim["id"],
        {"expected_revision": claim["revision"], "remark": "缺原因不能修改"},
        method="PATCH",
        status=422,
    )
    companies = get(client, "/catalogs")["companies"]
    wrong = next(x for x in companies if x["id"] != claim["company_id"])
    call(
        client,
        "/admin/cases/" + case["id"] + "/repair",
        {
            "reason": "错误修复应完整阻断",
            "patch": {"expected_revision": claim["revision"], "company_id": wrong["id"]},
        },
        status=422,
    )
    assert fresh(client, claim)["revision"] == claim["revision"]
    claim = call(
        client,
        "/admin/cases/" + case["id"] + "/repair",
        {
            "reason": "人工核对后补充说明",
            "patch": {"expected_revision": claim["revision"], "remark": "已核对公司及收款信息"},
        },
    )
    assert not get(client, "/review-reports/" + original_report["id"])["valid"]
    client.headers["X-Action-Reason"] = quote("协助完成修复后复核")
    report = review(client, claim)
    result = call(
        client,
        "/admin/cases/" + case["id"] + "/submit",
        {"reason": "确认修复后的完整申报", "expected_revision": claim["revision"], "review_id": report["id"]},
        status=202,
    )
    drain(["dispatch", "ledger"])
    event = next(e for e in get(client, "/ledger/events")["items"] if e["submission_id"] == result["id"])
    call(client, "/ledger/events/" + event["id"] + "/sync", {"reason": "生成本地模拟投影"})
    response = call(
        client,
        "/submissions/" + result["id"] + "/simulated-event",
        {"expected_state": "created", "state": "rejected", "reason": "模拟拒绝后核对台账"},
    )
    assert response["state"] == "rejected" and not response["conflicts"]
    assert all(
        e["status"] == "rolled_back"
        for e in get(client, "/ledger/entries")["items"]
        if e["event_id"] == event["id"]
    )
    call(client, "/ledger/events/" + event["id"] + "/sync", {"reason": "已拒绝不得重复投影"}, status=409)
