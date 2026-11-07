"""Require an independently entered claim total; preserve submitted history."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # Only auto-total drafts need a fresh human declaration. Keep manual drafts and locked history.
    op.execute(
        sa.text("""
        UPDATE app.review_reports SET valid = false
        WHERE claim_id IN (SELECT id FROM app.claims WHERE status = 'draft')
    """)
    )
    op.execute(
        sa.text("""
        UPDATE app.claims SET total_amount = NULL, total_auto = false,
            revision = revision + 1, updated_at = now()
        WHERE status = 'draft' AND total_auto
    """)
    )


def downgrade():
    raise RuntimeError("Independent human totals cannot be reconstructed as automatic declarations")
