"""Postgres access. Local development only — no Supabase (ADR-0002 deferred)."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar, cast

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from engine.config import settings

Conn = psycopg.Connection[DictRow]

_pool: ConnectionPool | None = None

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "db"


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=8,
            open=True,
            kwargs={"row_factory": dict_row},
        )
    return _pool


T = TypeVar("T")


def require(row: T | None, what: str = "row") -> T:
    """Assert a query that must return a row did. Keeps call sites free of None-checks."""
    if row is None:
        raise LookupError(f"expected {what} but found none")
    return row


@contextmanager
def connection() -> Iterator[Conn]:
    with pool().connection() as conn:
        yield cast(Conn, conn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def apply_schema(conn: Conn) -> None:
    """Apply migrations then seed. Forward-only and re-runnable (02 §7)."""
    for path in sorted((MIGRATIONS_DIR / "migrations").glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
    conn.execute((MIGRATIONS_DIR / "seed.sql").read_text(encoding="utf-8"))
    conn.commit()
