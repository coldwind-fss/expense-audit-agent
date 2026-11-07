from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, MetaData, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(schema="app")


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


engine = create_engine(settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Generator[Session]:
    with SessionLocal() as db:
        yield db
