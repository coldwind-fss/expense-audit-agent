"""New application schema and worker heartbeat."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        schema="app",
    )


def downgrade():
    op.drop_table("worker_heartbeats", schema="app")
