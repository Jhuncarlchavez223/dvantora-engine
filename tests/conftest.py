from __future__ import annotations

import os

import pytest

os.environ.setdefault("DVANTORA_ENV", "local")
os.environ.setdefault(
    "DVANTORA_DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/dvantora"),
)

from engine import db  # noqa: E402
from engine.api.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema():
    with db.connection() as conn:
        db.apply_schema(conn)
    yield
    db.close_pool()


@pytest.fixture(autouse=True)
def clean_runs():
    """Each test starts with no runs. Taxonomy seed rows are left in place."""
    with db.connection() as conn:
        conn.execute("TRUNCATE research_runs CASCADE")
        conn.execute("TRUNCATE events_outbox")
        conn.execute("DELETE FROM market_aliases")
        conn.commit()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture
def conn():
    with db.connection() as c:
        yield c
