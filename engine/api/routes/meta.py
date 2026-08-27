"""Health, taxonomy and market resolution (05 §2, §5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from engine.db import connection
from engine.markets import resolver

router = APIRouter()


class ResolveRequest(BaseModel):
    service: str = Field(min_length=1)
    location: str = Field(min_length=1)


@router.get("/health")
def health() -> dict[str, str]:
    with connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/services")
def list_services() -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT slug, display_name, anzsic_code FROM services WHERE is_active ORDER BY slug"
        ).fetchall()
    return {"items": rows}


@router.post("/markets/resolve")
def resolve_market(body: ResolveRequest) -> dict[str, Any]:
    with connection() as conn:
        res = resolver.resolve(conn, body.service, body.location)
        conn.commit()
    return {
        "resolved": True,
        "market": {
            "market_key": res.market_key,
            "service": res.service,
            "location": res.location,
            "resolution": {"method": res.method.value, "confidence": res.confidence},
        },
    }
