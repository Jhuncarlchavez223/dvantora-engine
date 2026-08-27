"""Auth stub for local development only (05 §1.1).

Supabase issues real JWTs (ADR-0002) but Supabase is out of scope for the
walking skeleton. This resolves a fixed local account and REFUSES to run outside
`DVANTORA_ENV=local`, so it cannot be deployed by accident.
"""

from __future__ import annotations

import uuid
from typing import Any

from engine.config import settings
from engine.db import Conn, require
from engine.errors import ApiError

DEV_ACCOUNT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def current_account(conn: Conn) -> dict[str, Any]:
    if settings.env != "local":
        raise ApiError(
            401,
            "unauthenticated",
            "Real authentication is not implemented; the dev principal is local-only.",
        )
    row = conn.execute("SELECT * FROM accounts WHERE id = %s", (DEV_ACCOUNT_ID,)).fetchone()
    if row:
        return row
    return require(
        conn.execute(
            "INSERT INTO accounts (id, email, display_name, access_tier) "
            "VALUES (%s,%s,%s,'internal') RETURNING *",
            (DEV_ACCOUNT_ID, settings.dev_account_email, "Local Developer"),
        ).fetchone(),
        "dev account",
    )
