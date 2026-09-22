from __future__ import annotations

import os

import pytest

os.environ["DVANTORA_COLLECTOR_MODE"] = "fixture"

os.environ.setdefault("DVANTORA_ENV", "local")

# The tests empty the runs tables before every test, so they must NEVER point at
# the development database. They use their own database, dvantora_test. This
# overrides DVANTORA_DATABASE_URL from .env for the test process only.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/dvantora_test"
)
_test_db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
if not _test_db_name.endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests against database {_test_db_name!r}: the tests delete "
        "data, so TEST_DATABASE_URL must name a database ending in '_test'."
    )
os.environ["DVANTORA_DATABASE_URL"] = TEST_DATABASE_URL

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
