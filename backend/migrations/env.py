from alembic import context
from sqlalchemy import text

from reimbursement.db import Base, engine
from reimbursement import models  # noqa: F401


def run():
    with engine.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS agent_runtime"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            version_table_schema="app",
            include_schemas=True,
            include_name=lambda name, kind, parents: kind != "schema" or name == "app",
        )
        with context.begin_transaction():
            context.run_migrations()


run()
