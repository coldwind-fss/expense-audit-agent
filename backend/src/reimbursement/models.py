from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, Record, now


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(30), default="running")


class Workspace(Record, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(100), default="独立体验空间")


class Scoped:
    workspace_id: Mapped[str] = mapped_column(ForeignKey("app.workspaces.id"), index=True)


class Company(Record, Scoped, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(200))


class Department(Record, Scoped, Base):
    __tablename__ = "departments"
    name: Mapped[str] = mapped_column(String(100))


class Employee(Record, Scoped, Base):
    __tablename__ = "employees"
    name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[str] = mapped_column(ForeignKey("app.departments.id"))
    social_company_id: Mapped[str | None] = mapped_column(ForeignKey("app.companies.id"))
    persona: Mapped[str] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(30), default="employee")
    can_on_behalf: Mapped[bool] = mapped_column(Boolean, default=False)
    invoice_only: Mapped[bool] = mapped_column(Boolean, default=False)


class SessionRecord(Record, Scoped, Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(100))
    employee_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Account(Record, Scoped, Base):
    __tablename__ = "recipient_accounts"
    employee_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    ciphertext: Mapped[str] = mapped_column(Text)
    masked: Mapped[str] = mapped_column(String(200))


class Claim(Record, Scoped, Base):
    __tablename__ = "claims"
    title: Mapped[str] = mapped_column(String(200), default="新的报销")
    workflow_key: Mapped[str] = mapped_column(String(30), default="daily")
    route_mode: Mapped[str] = mapped_column(String(30), default="self")
    actor_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    subject_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    originator_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    department_id: Mapped[str] = mapped_column(ForeignKey("app.departments.id"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("app.companies.id"))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("app.recipient_accounts.id"))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # Kept for historical snapshots; new claims always use an independently entered total.
    total_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    related_ids: Mapped[list] = mapped_column(JSONB, default=list)
    remark: Mapped[str] = mapped_column(Text, default="")
    travel_date_remark: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClaimLine(Record, Scoped, Base):
    __tablename__ = "claim_lines"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    business_date: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    project: Mapped[str] = mapped_column(String(100), default="")
    expense_type: Mapped[str] = mapped_column(String(30), default="")
    invoice_type: Mapped[str] = mapped_column(String(30), default="")
    related_id: Mapped[str | None] = mapped_column(ForeignKey("app.related_approvals.id"))
    remark: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[dict] = mapped_column(JSONB, default=dict)


class RelatedApproval(Record, Scoped, Base):
    __tablename__ = "related_approvals"
    employee_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    business_id: Mapped[str] = mapped_column(String(100))
    approval_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="approved")


class ClaimRevision(Record, Scoped, Base):
    __tablename__ = "claim_revisions"
    __table_args__ = (UniqueConstraint("claim_id", "revision"),)
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"))
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)


class AuditEvent(Record, Scoped, Base):
    __tablename__ = "audit_events"
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("app.claims.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class IdempotencyRecord(Record, Scoped, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("workspace_id", "actor_id", "scope", "key"),)
    actor_id: Mapped[str] = mapped_column(String(36))
    scope: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(150))
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB, default=dict)


class Material(Record, Scoped, Base):
    __tablename__ = "materials"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"), index=True)
    name: Mapped[str] = mapped_column(String(250))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    line_id: Mapped[str | None] = mapped_column(ForeignKey("app.claim_lines.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    error: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[list] = mapped_column(JSONB, default=list)
    fixture_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    fact_version: Mapped[int] = mapped_column(Integer, default=0)
    manual_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    duplicate_of: Mapped[str | None] = mapped_column(String(36))
    duplicate_kind: Mapped[str] = mapped_column(String(30), default="")
    duplicate_decision: Mapped[str] = mapped_column(String(30), default="")


class MaterialFact(Record, Scoped, Base):
    __tablename__ = "material_facts"
    __table_args__ = (UniqueConstraint("material_id", "version"),)
    material_id: Mapped[str] = mapped_column(ForeignKey("app.materials.id"))
    version: Mapped[int] = mapped_column(Integer)
    facts: Mapped[dict] = mapped_column(JSONB)
    run_id: Mapped[str] = mapped_column(String(36))


class HumanDecision(Record, Scoped, Base):
    __tablename__ = "human_decisions"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"))
    material_id: Mapped[str | None] = mapped_column(ForeignKey("app.materials.id"))
    actor_id: Mapped[str] = mapped_column(String(36))
    decision_type: Mapped[str] = mapped_column(String(40))
    value: Mapped[dict] = mapped_column(JSONB)


class AgentRun(Record, Scoped, Base):
    __tablename__ = "agent_runs"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"), index=True)
    material_id: Mapped[str | None] = mapped_column(ForeignKey("app.materials.id"))
    task_kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    input_revision: Mapped[int] = mapped_column(Integer)
    input_signature: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    execution_mode: Mapped[str] = mapped_column(String(30), default="fixture")
    output: Mapped[dict] = mapped_column(JSONB, default=dict)
    stop_reason: Mapped[str] = mapped_column(String(100), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempt_id: Mapped[str] = mapped_column(String(36))
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    question: Mapped[dict] = mapped_column(JSONB, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(Record, Scoped, Base):
    __tablename__ = "agent_steps"
    run_id: Mapped[str] = mapped_column(ForeignKey("app.agent_runs.id"), index=True)
    node: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class Job(Record, Scoped, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("jobs_pending", "status", "available_at"),)
    kind: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class SuggestionBatch(Record, Scoped, Base):
    __tablename__ = "suggestion_batches"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("app.agent_runs.id"))
    input_revision: Mapped[int] = mapped_column(Integer)
    items: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    applied_values: Mapped[list] = mapped_column(JSONB, default=list)


class ReviewReport(Record, Scoped, Base):
    __tablename__ = "review_reports"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("app.agent_runs.id"))
    input_revision: Mapped[int] = mapped_column(Integer)
    input_signature: Mapped[str] = mapped_column(String(64))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    can_submit: Mapped[bool] = mapped_column(Boolean, default=False)
    checks: Mapped[list] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    execution_mode: Mapped[str] = mapped_column(String(30), default="fixture")


class Submission(Record, Scoped, Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("claim_id"),)
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"))
    review_id: Mapped[str] = mapped_column(ForeignKey("app.review_reports.id"))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    simulated_reference: Mapped[str | None] = mapped_column(String(100))
    failure: Mapped[str] = mapped_column(Text, default="")
    fault: Mapped[str] = mapped_column(String(50), default="")


class GatewayResult(Record, Scoped, Base):
    __tablename__ = "gateway_results"
    submission_id: Mapped[str] = mapped_column(ForeignKey("app.submissions.id"), unique=True)
    simulated_reference: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="created")


class DispatchGuard(Base):
    __tablename__ = "dispatch_guard"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("app.workspaces.id"), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)


class SupportCase(Record, Scoped, Base):
    __tablename__ = "support_cases"
    claim_id: Mapped[str] = mapped_column(ForeignKey("app.claims.id"))
    subject_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class AdminAction(Record, Scoped, Base):
    __tablename__ = "admin_actions"
    case_id: Mapped[str | None] = mapped_column(ForeignKey("app.support_cases.id"))
    actor_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class LedgerEvent(Record, Scoped, Base):
    __tablename__ = "ledger_events"
    submission_id: Mapped[str] = mapped_column(ForeignKey("app.submissions.id"), unique=True)
    month: Mapped[str] = mapped_column(String(7))
    mode: Mapped[str] = mapped_column(String(20), default="audit")
    status: Mapped[str] = mapped_column(String(30), default="audited")
    candidates: Mapped[list] = mapped_column(JSONB, default=list)
    issues: Mapped[list] = mapped_column(JSONB, default=list)


class LedgerEntry(Record, Scoped, Base):
    __tablename__ = "ledger_entries"
    event_id: Mapped[str] = mapped_column(ForeignKey("app.ledger_events.id"))
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)
    values: Mapped[list] = mapped_column(JSONB)
    original_values: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="simulated_synced")


class FeedbackInvitation(Record, Scoped, Base):
    __tablename__ = "feedback_invitations"
    __table_args__ = (UniqueConstraint("workspace_id", "employee_id", "campaign"),)
    employee_id: Mapped[str] = mapped_column(ForeignKey("app.employees.id"))
    campaign: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="simulated_sent")
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeedbackAnswer(Record, Scoped, Base):
    __tablename__ = "feedback_answers"
    invitation_id: Mapped[str] = mapped_column(ForeignKey("app.feedback_invitations.id"), unique=True)
    difficulty: Mapped[str] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(50))
    suggestion: Mapped[str] = mapped_column(String(500), default="")


# Critical parent-child links carry the workspace at the database boundary too.
# Ordinary single-column keys remain convenient for ORM lookup and SET NULL.
_scoped_links = [
    (Employee, "department_id", Department),
    (Employee, "social_company_id", Company),
    (SessionRecord, "employee_id", Employee),
    (Account, "employee_id", Employee),
    (Claim, "actor_id", Employee),
    (Claim, "subject_id", Employee),
    (Claim, "originator_id", Employee),
    (Claim, "company_id", Company),
    (Claim, "account_id", Account),
    (ClaimLine, "claim_id", Claim),
    (ClaimLine, "related_id", RelatedApproval),
    (Material, "claim_id", Claim),
    (Material, "line_id", ClaimLine),
    (AgentRun, "claim_id", Claim),
    (AgentRun, "material_id", Material),
    (ReviewReport, "claim_id", Claim),
    (Submission, "claim_id", Claim),
    (Submission, "review_id", ReviewReport),
    (SupportCase, "claim_id", Claim),
    (SupportCase, "subject_id", Employee),
    (FeedbackInvitation, "employee_id", Employee),
    (FeedbackAnswer, "invitation_id", FeedbackInvitation),
]
for _parent in {_link[2] for _link in _scoped_links}:
    Base.metadata.tables[f"app.{_parent.__tablename__}"].append_constraint(
        UniqueConstraint("id", "workspace_id", name=f"uq_{_parent.__tablename__}_scope")
    )
for _child, _column, _parent in _scoped_links:
    Base.metadata.tables[f"app.{_child.__tablename__}"].append_constraint(
        ForeignKeyConstraint(
            [_column, "workspace_id"],
            [f"app.{_parent.__tablename__}.id", f"app.{_parent.__tablename__}.workspace_id"],
            name=f"fk_{_child.__tablename__}_{_column}_scope",
        )
    )
