"""Shared test fixtures: each test gets a fresh in-memory database.

C# analogy: a test fixture that swaps the DbContext for an in-memory provider.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ledger.db import Base, get_session
from ledger.main import create_app


@contextmanager
def client_for(engine: Engine) -> Iterator[TestClient]:
    """A TestClient for a fresh app whose sessions use `engine`."""
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with TestSession() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with client_for(engine) as c:
        yield c
