from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .catalogs import EXPENSE_TYPES, INVOICE_TYPES, PROJECTS, WORKFLOWS
from .config import settings
from .db import get_db
from .errors import AppError
from .model_gateway import model_profile
from .models import (
    Account,
    Claim,
    ClaimLine,
    ClaimRevision,
    Company,
    Department,
    Employee,
    RelatedApproval,
    SessionRecord,
)
from .schemas import (
    AccountInput,
    ClaimCreate,
    ClaimPatch,
    ClaimView,
    LineInput,
    LinePatch,
    PersonaInput,
    RevisionInput,
)
from .security import (
    Context,
    check_origin,
    create_experience,
    current_context,
    encrypt,
    require_admin,
    token_hash,
)
from .services import audit, bump_claim, check_revision, claim_view, command, load_claim, scoped

router = APIRouter(prefix="/api/v1")


def me_view(db: Session, context: Context):
    people = db.scalars(select(Employee).where(Employee.workspace_id == context.workspace_id)).all()
    return {
        "workspace_id": context.workspace_id,
        "csrf_token": context.session.csrf,
        "actor": {
            "id": context.actor.id,
            "name": context.actor.name,
            "role": context.actor.role,
            "persona": context.actor.persona,
            "invoice_only": context.actor.invoice_only,
            "can_on_behalf": context.actor.can_on_behalf,
            "social_company_id": context.actor.social_company_id,
        },
        "personas": [{"key": p.persona, "name": p.name, "role": p.role} for p in people],
        "enterprise_mode": "stub",
        "model_mode": settings().model_mode,
        "model_profile": model_profile(),
        "provider_configured": bool(settings().model_api_key.get_secret_value()),
    }


@router.post("/experience/sessions", status_code=201)
def experience(request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    token = request.cookies.get("reimbursement_session", "")
    existing = db.scalar(select(SessionRecord).where(SessionRecord.token_hash == token_hash(token)))
    from .db import now

    if existing and existing.expires_at > now():
        return me_view(db, Context(existing, db.get_one(Employee, existing.employee_id)))
    session, token = create_experience(db)
    db.commit()
    response.set_cookie(
        "reimbursement_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        max_age=8 * 3600,
    )
    return me_view(db, Context(session, db.get_one(Employee, session.employee_id)))


@router.get("/me")
def me(context: Context = Depends(current_context), db: Session = Depends(get_db)):
    return me_view(db, context)


@router.post("/experience/persona")
def persona(body: PersonaInput, context: Context = Depends(current_context), db: Session = Depends(get_db)):
    actor = db.scalar(
        select(Employee).where(
            Employee.workspace_id == context.workspace_id, Employee.persona == body.persona
        )
    )
    if not actor:
        raise AppError("FORBIDDEN", "该体验身份不可用", 403)
    context.session.employee_id = actor.id
    context.actor = actor
    db.commit()
    return me_view(db, context)


@router.get("/capabilities")
def capabilities(context: Context = Depends(current_context)):
    return {
        "model_mode": settings().model_mode,
        "enterprise_mode": "stub",
        "real_oa": False,
        "scheduling_enabled": settings().scheduling_enabled,
        "max_file_bytes": 50_000_000,
        "invoice_only": context.actor.invoice_only,
        "admin": context.actor.role == "admin",
    }


@router.get("/catalogs")
def catalogs(context: Context = Depends(current_context), db: Session = Depends(get_db)):
    return {
        "workflows": [w for w in WORKFLOWS if w["key"] != "supply_chain" or context.actor.invoice_only],
        "companies": [
            {"id": c.id, "name": c.name}
            for c in db.scalars(select(Company).where(Company.workspace_id == context.workspace_id))
        ],
        "departments": [
            {"id": d.id, "name": d.name}
            for d in db.scalars(select(Department).where(Department.workspace_id == context.workspace_id))
        ],
        "projects": PROJECTS,
        "expense_types": EXPENSE_TYPES,
        "invoice_types": INVOICE_TYPES,
    }


@router.get("/employees")
def employees(context: Context = Depends(current_context), db: Session = Depends(get_db)):
    if not context.actor.can_on_behalf and context.actor.role != "admin":
        people = [context.actor]
    else:
        people = list(db.scalars(select(Employee).where(Employee.workspace_id == context.workspace_id)).all())
    return {
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "department_id": p.department_id,
                "social_company_id": p.social_company_id,
            }
            for p in people
        ],
        "next_cursor": None,
        "has_more": False,
    }


@router.get("/related-approvals")
def related(
    employee_id: str | None = None, context: Context = Depends(current_context), db: Session = Depends(get_db)
):
    subject = scoped(db, Employee, employee_id or context.actor.id, context.workspace_id)
    if subject.id != context.actor.id and not context.actor.can_on_behalf and context.actor.role != "admin":
        raise AppError("FORBIDDEN", "无权查询该归属人的审批", 403)
    rows = db.scalars(
        select(RelatedApproval).where(
            RelatedApproval.employee_id == subject.id, RelatedApproval.workspace_id == context.workspace_id
        )
    ).all()
    return {
        "items": [
            {
                "id": a.id,
                "business_id": a.business_id,
                "title": a.title,
                "approval_type": a.approval_type,
                "employee_id": a.employee_id,
                "start_date": str(a.start_date),
                "end_date": str(a.end_date),
                "status": a.status,
                "adapter_mode": "stub",
            }
            for a in rows
        ],
        "next_cursor": None,
        "has_more": False,
    }


@router.get("/related-approvals/resolve")
def resolve_approval(
    business_id: str,
    employee_id: str | None = None,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    result = related(employee_id, context, db)
    found = next(
        (row for row in result["items"] if row["business_id"].casefold() == business_id.strip().casefold()),
        None,
    )
    if not found:
        raise AppError("RESOURCE_NOT_FOUND", "合成目录中没有该归属人的业务号；当前未连接真实企业查询", 404)
    return found


def route_identity(db: Session, context: Context, mode: str, subject_id: str | None):
    if mode == "admin_originator":
        require_admin(context)
    if mode == "on_behalf" and not context.actor.can_on_behalf and context.actor.role != "admin":
        raise AppError("FORBIDDEN", "当前身份没有代报权限", 403)
    subject = (
        context.actor
        if mode == "self"
        else scoped(db, Employee, subject_id or context.actor.id, context.workspace_id)
    )
    return subject, subject.id if mode == "admin_originator" else context.actor.id


def ensure_workflow(context: Context, workflow_key: str):
    if workflow_key == "supply_chain" and not context.actor.invoice_only:
        raise AppError("FORBIDDEN", "采购供应链入口仅对授权身份开放", 403)


def create_claim(db: Session, context: Context, body: ClaimCreate) -> Claim:
    ensure_workflow(context, body.workflow_key)
    subject, originator_id = route_identity(db, context, body.route_mode, body.subject_id)
    claim = Claim(
        workspace_id=context.workspace_id,
        title=body.title,
        workflow_key=body.workflow_key,
        route_mode=body.route_mode,
        actor_id=context.actor.id,
        subject_id=subject.id,
        originator_id=originator_id,
        department_id=subject.department_id,
        company_id=subject.social_company_id,
    )
    db.add(claim)
    db.flush()
    db.add(
        ClaimRevision(
            workspace_id=context.workspace_id, claim_id=claim.id, revision=1, snapshot=claim_view(db, claim)
        )
    )
    audit(db, context, "claim.created", claim.id)
    return claim


@router.post("/claims", response_model=ClaimView, status_code=201)
def post_claim(
    body: ClaimCreate,
    request: Request,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    return command(
        db,
        context,
        request.headers.get("idempotency-key"),
        "claim.create",
        body.model_dump(),
        lambda: claim_view(db, create_claim(db, context, body)),
    )


@router.get("/claims")
def claims(cursor: int = 0, context: Context = Depends(current_context), db: Session = Depends(get_db)):
    query = select(Claim).where(Claim.workspace_id == context.workspace_id)
    if context.actor.role != "admin":
        query = query.where(Claim.actor_id == context.actor.id)
    rows = db.scalars(query.order_by(Claim.updated_at.desc()).offset(max(0, cursor)).limit(51)).all()
    return {
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "workflow_key": c.workflow_key,
                "status": c.status,
                "total_amount": str(c.total_amount or "0.00"),
                "updated_at": c.updated_at.isoformat(),
                "revision": c.revision,
            }
            for c in rows[:50]
        ],
        "has_more": len(rows) > 50,
        "next_cursor": str(cursor + 50) if len(rows) > 50 else None,
    }


@router.get("/claims/{claim_id}", response_model=ClaimView)
def get_claim(claim_id: str, context: Context = Depends(current_context), db: Session = Depends(get_db)):
    return claim_view(db, load_claim(db, context, claim_id))


def patch_claim(db: Session, context: Context, claim: Claim, body: ClaimPatch):
    check_revision(claim, body.expected_revision)
    fields = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if "workflow_key" in fields:
        ensure_workflow(context, fields["workflow_key"])
    if "route_mode" in fields or "subject_id" in fields:
        subject, originator = route_identity(
            db,
            context,
            fields.get("route_mode", claim.route_mode),
            fields.get("subject_id", claim.subject_id),
        )
        fields.update(subject_id=subject.id, originator_id=originator, department_id=subject.department_id)
        fields["related_ids"] = []
        for line in db.scalars(select(ClaimLine).where(ClaimLine.claim_id == claim.id)):
            line.related_id = None
    if fields.get("company_id"):
        scoped(db, Company, fields["company_id"], context.workspace_id)
    if fields.get("department_id"):
        department = scoped(db, Department, fields["department_id"], context.workspace_id)
        subject = db.get_one(Employee, fields.get("subject_id", claim.subject_id))
        if department.id != subject.department_id:
            raise AppError("FORBIDDEN", "部门不属于当前报销归属人", 403)
    if fields.get("account_id"):
        account = scoped(db, Account, fields["account_id"], context.workspace_id)
        if account.employee_id != claim.actor_id and context.actor.role != "admin":
            raise AppError("FORBIDDEN", "该收款账户不在当前操作人的账户列表中", 403)
    for approval_id in fields.get("related_ids") or []:
        approval = scoped(db, RelatedApproval, approval_id, context.workspace_id)
        if approval.employee_id != fields.get("subject_id", claim.subject_id):
            raise AppError("FORBIDDEN", "关联审批不属于当前报销归属人", 403)
    if "total_amount" in fields and "total_auto" not in fields:
        fields["total_auto"] = False
    for name, value in fields.items():
        setattr(claim, name, value)
    bump_claim(db, context, claim, "claim.updated")


@router.patch("/claims/{claim_id}", response_model=ClaimView)
def update_claim(
    claim_id: str,
    body: ClaimPatch,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    patch_claim(db, context, claim, body)
    db.commit()
    return claim_view(db, claim)


def validate_line_relation(db: Session, context: Context, claim: Claim, related_id):
    if related_id:
        approval = scoped(db, RelatedApproval, related_id, context.workspace_id)
        if approval.employee_id != claim.subject_id:
            raise AppError("FORBIDDEN", "该行审批不属于报销归属人", 403)


@router.post("/claims/{claim_id}/lines", response_model=ClaimView, status_code=201)
def add_line(
    claim_id: str, body: LineInput, context: Context = Depends(current_context), db: Session = Depends(get_db)
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    validate_line_relation(db, context, claim, body.related_id)
    fields = body.model_dump(exclude={"expected_revision"})
    if claim.workflow_key == "no_invoice":
        fields["invoice_type"] = "无"
    sources = {
        key: {"kind": "manual", "revision": claim.revision + 1}
        for key in fields
        if fields[key] not in (None, "")
    }
    line = ClaimLine(
        workspace_id=context.workspace_id,
        claim_id=claim.id,
        position=db.scalar(select(func.count()).select_from(ClaimLine).where(ClaimLine.claim_id == claim.id)),
        sources=sources,
        **fields,
    )
    db.add(line)
    bump_claim(db, context, claim, "line.created")
    db.commit()
    return claim_view(db, claim)


@router.patch("/claims/{claim_id}/lines/{line_id}", response_model=ClaimView)
def edit_line(
    claim_id: str,
    line_id: str,
    body: LinePatch,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    line = scoped(db, ClaimLine, line_id, context.workspace_id)
    if line.claim_id != claim.id:
        raise AppError("RESOURCE_NOT_FOUND", "明细不属于此报销", 404)
    values = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    validate_line_relation(db, context, claim, values.get("related_id"))
    for key, value in values.items():
        if key in {"reason", "project", "expense_type", "invoice_type", "remark"}:
            value = value or ""
        setattr(line, key, value)
    line.sources = {
        **line.sources,
        **{key: {"kind": "manual", "revision": claim.revision + 1} for key in values},
    }
    if claim.workflow_key == "no_invoice":
        line.invoice_type = "无"
    bump_claim(db, context, claim, "line.updated")
    db.commit()
    return claim_view(db, claim)


@router.post("/claims/{claim_id}/lines/{line_id}/copy", response_model=ClaimView)
def copy_line(
    claim_id: str,
    line_id: str,
    body: RevisionInput,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    line = scoped(db, ClaimLine, line_id, context.workspace_id)
    if line.claim_id != claim.id:
        raise AppError("RESOURCE_NOT_FOUND", "明细不属于此报销", 404)
    fields = {
        key: getattr(line, key)
        for key in [
            "business_date",
            "reason",
            "amount",
            "project",
            "expense_type",
            "invoice_type",
            "related_id",
            "remark",
        ]
    }
    db.add(
        ClaimLine(
            workspace_id=context.workspace_id,
            claim_id=claim.id,
            position=line.position + 1,
            sources={key: {"kind": "manual"} for key in fields},
            **fields,
        )
    )
    bump_claim(db, context, claim, "line.copied_without_attachments")
    db.commit()
    return claim_view(db, claim)


@router.delete("/claims/{claim_id}/lines/{line_id}", response_model=ClaimView)
def delete_line(
    claim_id: str,
    line_id: str,
    expected_revision: int,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    check_revision(claim, expected_revision)
    line = scoped(db, ClaimLine, line_id, context.workspace_id)
    if line.claim_id != claim.id:
        raise AppError("RESOURCE_NOT_FOUND", "明细不属于此报销", 404)
    db.delete(line)
    bump_claim(db, context, claim, "line.deleted")
    db.commit()
    return claim_view(db, claim)


@router.get("/recipient-accounts")
def accounts(context: Context = Depends(current_context), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Account).where(
            Account.workspace_id == context.workspace_id, Account.employee_id == context.actor.id
        )
    ).all()
    return {
        "items": [{"id": a.id, "label": a.label, "kind": a.kind, "masked": a.masked} for a in rows],
        "next_cursor": None,
        "has_more": False,
    }


@router.post("/recipient-accounts", status_code=201)
def add_account(
    body: AccountInput, context: Context = Depends(current_context), db: Session = Depends(get_db)
):
    account = Account(
        workspace_id=context.workspace_id,
        employee_id=context.actor.id,
        label=body.label,
        kind=body.kind,
        ciphertext=encrypt(body.value),
        masked=f"•••• {body.value[-4:] if len(body.value) > 8 else body.value[-2:]}",
    )
    db.add(account)
    db.commit()
    return {"id": account.id, "label": account.label, "kind": account.kind, "masked": account.masked}


@router.patch("/recipient-accounts/{account_id}")
def edit_account(
    account_id: str,
    body: AccountInput,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    account = scoped(db, Account, account_id, context.workspace_id)
    if account.employee_id != context.actor.id:
        raise AppError("FORBIDDEN", "只能修改自己的账户", 403)
    account.label, account.kind, account.ciphertext = body.label, body.kind, encrypt(body.value)
    account.masked = f"•••• {body.value[-4:] if len(body.value) > 8 else body.value[-2:]}"
    db.commit()
    return {"id": account.id, "label": account.label, "kind": account.kind, "masked": account.masked}


@router.delete("/recipient-accounts/{account_id}")
def delete_account(
    account_id: str, context: Context = Depends(current_context), db: Session = Depends(get_db)
):
    account = scoped(db, Account, account_id, context.workspace_id)
    if account.employee_id != context.actor.id:
        raise AppError("FORBIDDEN", "只能删除自己的账户", 403)
    if db.scalar(select(Claim.id).where(Claim.account_id == account.id).limit(1)):
        raise AppError("INVALID_STATE", "账户仍被报销引用，请先更换报销账户", 409)
    db.delete(account)
    db.commit()
    return {"deleted": True}
