"""workspace_constraints"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_claim_lines_scope", "claim_lines", ["id", "workspace_id"], schema="app")
    op.create_unique_constraint("uq_claims_scope", "claims", ["id", "workspace_id"], schema="app")
    op.create_unique_constraint("uq_companies_scope", "companies", ["id", "workspace_id"], schema="app")
    op.create_unique_constraint("uq_departments_scope", "departments", ["id", "workspace_id"], schema="app")
    op.create_unique_constraint("uq_employees_scope", "employees", ["id", "workspace_id"], schema="app")
    op.create_unique_constraint(
        "uq_feedback_invitations_scope", "feedback_invitations", ["id", "workspace_id"], schema="app"
    )
    op.create_unique_constraint("uq_materials_scope", "materials", ["id", "workspace_id"], schema="app")
    op.create_unique_constraint(
        "uq_recipient_accounts_scope", "recipient_accounts", ["id", "workspace_id"], schema="app"
    )
    op.create_unique_constraint(
        "uq_related_approvals_scope", "related_approvals", ["id", "workspace_id"], schema="app"
    )
    op.create_unique_constraint(
        "uq_review_reports_scope", "review_reports", ["id", "workspace_id"], schema="app"
    )
    op.create_foreign_key(
        "fk_agent_runs_claim_id_scope",
        "agent_runs",
        "claims",
        ["claim_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_agent_runs_material_id_scope",
        "agent_runs",
        "materials",
        ["material_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claim_lines_claim_id_scope",
        "claim_lines",
        "claims",
        ["claim_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claim_lines_related_id_scope",
        "claim_lines",
        "related_approvals",
        ["related_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claims_actor_id_scope",
        "claims",
        "employees",
        ["actor_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claims_subject_id_scope",
        "claims",
        "employees",
        ["subject_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claims_account_id_scope",
        "claims",
        "recipient_accounts",
        ["account_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claims_company_id_scope",
        "claims",
        "companies",
        ["company_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_claims_originator_id_scope",
        "claims",
        "employees",
        ["originator_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_employees_social_company_id_scope",
        "employees",
        "companies",
        ["social_company_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_employees_department_id_scope",
        "employees",
        "departments",
        ["department_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_feedback_answers_invitation_id_scope",
        "feedback_answers",
        "feedback_invitations",
        ["invitation_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_feedback_invitations_employee_id_scope",
        "feedback_invitations",
        "employees",
        ["employee_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_materials_line_id_scope",
        "materials",
        "claim_lines",
        ["line_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_materials_claim_id_scope",
        "materials",
        "claims",
        ["claim_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_recipient_accounts_employee_id_scope",
        "recipient_accounts",
        "employees",
        ["employee_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_review_reports_claim_id_scope",
        "review_reports",
        "claims",
        ["claim_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_sessions_employee_id_scope",
        "sessions",
        "employees",
        ["employee_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_submissions_claim_id_scope",
        "submissions",
        "claims",
        ["claim_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_submissions_review_id_scope",
        "submissions",
        "review_reports",
        ["review_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_support_cases_claim_id_scope",
        "support_cases",
        "claims",
        ["claim_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_foreign_key(
        "fk_support_cases_subject_id_scope",
        "support_cases",
        "employees",
        ["subject_id", "workspace_id"],
        ["id", "workspace_id"],
        source_schema="app",
        referent_schema="app",
    )
    # ### end Alembic commands ###


def downgrade():
    raise RuntimeError("Use a reviewed forward migration; automatic constraint removal is not provided.")
