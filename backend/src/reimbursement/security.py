import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import unquote

from cryptography.fernet import Fernet
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, now
from .errors import AppError
from .models import Company, Department, Employee, RelatedApproval, SessionRecord, Workspace


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def encrypt(value: str) -> str:
    key_file = settings().file_root.resolve().parent / "app.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        try:
            with key_file.open("xb") as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass
    return Fernet(key_file.read_bytes()).encrypt(value.encode()).decode()


@dataclass
class Context:
    session: SessionRecord
    actor: Employee
    action_reason: str = ""

    @property
    def workspace_id(self) -> str:
        return self.session.workspace_id


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin not in settings().allowed_origins:
        raise AppError("FORBIDDEN", "请求来源不被允许", 403)


def current_context(request: Request, db: Session = Depends(get_db)) -> Context:
    token = request.cookies.get("reimbursement_session", "")
    session = db.scalar(select(SessionRecord).where(SessionRecord.token_hash == token_hash(token)))
    if not session or session.expires_at < now():
        raise AppError("SESSION_EXPIRED", "体验会话已过期，请重新进入", 401)
    request.state.workspace_id = session.workspace_id
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
            raise AppError("FORBIDDEN", "请求缺少有效的会话确认", 403)
    actor = db.get_one(Employee, session.employee_id)
    if not actor:
        raise AppError("SESSION_EXPIRED", "当前体验身份不可用", 401)
    return Context(session, actor, unquote(request.headers.get("x-action-reason", "")))


def require_admin(context: Context):
    if context.actor.role != "admin":
        raise AppError("FORBIDDEN", "需要管理员权限", 403)


def create_experience(db: Session) -> tuple[SessionRecord, str]:
    workspace = Workspace()
    db.add(workspace)
    db.flush()
    w = workspace.id
    companies = [Company(workspace_id=w, name=n) for n in ["青禾科技有限公司", "青禾供应链有限公司"]]
    departments = [Department(workspace_id=w, name=n) for n in ["产品研发部", "运营管理部"]]
    db.add_all([*companies, *departments])
    db.flush()
    employees = [
        Employee(
            workspace_id=w,
            name="陈晓",
            persona="employee",
            role="employee",
            department_id=departments[0].id,
            social_company_id=companies[0].id,
            can_on_behalf=True,
        ),
        Employee(
            workspace_id=w,
            name="林悦",
            persona="colleague",
            role="employee",
            department_id=departments[1].id,
            social_company_id=companies[0].id,
        ),
        Employee(
            workspace_id=w,
            name="王宁",
            persona="admin",
            role="admin",
            department_id=departments[1].id,
            social_company_id=companies[0].id,
            can_on_behalf=True,
            invoice_only=True,
        ),
    ]
    db.add_all(employees)
    db.flush()
    today = now().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).date()
    for employee in employees:
        for kind, name in [
            ("travel", "杭州客户交流出差申请"),
            ("outing", "市内外出申请"),
            ("team", "部门活动特别审批"),
        ]:
            db.add(
                RelatedApproval(
                    workspace_id=w,
                    employee_id=employee.id,
                    business_id=f"SYN-{kind.upper()}-{employee.persona}",
                    approval_type=kind,
                    title=name,
                    start_date=today - timedelta(days=7),
                    end_date=today + timedelta(days=7),
                )
            )
    token = secrets.token_urlsafe(32)
    session = SessionRecord(
        workspace_id=w,
        token_hash=token_hash(token),
        csrf=secrets.token_urlsafe(24),
        employee_id=employees[0].id,
        expires_at=now() + timedelta(hours=8),
    )
    db.add(session)
    db.flush()
    return session, token
