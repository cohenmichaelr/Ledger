"""Database engine + session handling (SQLAlchemy 2.0).

C# analogy: Engine ~ connection factory, Session ~ DbContext (unit of work).
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ledger.config import get_settings


class Base(DeclarativeBase):
    """All ORM models inherit from this."""


def make_engine(url: str):
    # SQLite + FastAPI's threadpool needs check_same_thread=False
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request (like a scoped DbContext)."""
    with SessionLocal() as session:
        yield session


# Type alias for route params:  def handler(session: SessionDep): ...
# (FastAPI sees Depends() and injects a session — like constructor DI in ASP.NET)
SessionDep = Annotated[Session, Depends(get_session)]
