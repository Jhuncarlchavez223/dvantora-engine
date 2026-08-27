"""Canonical market resolution (00 §2, 02 §3.5, 05 §5).

The rule that matters: when confidence is below threshold, or two candidates are
too close to separate, this module refuses to guess and the API returns
409 market_ambiguous. A confident report about the wrong market is the worst
failure this product has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from engine.config import settings
from engine.db import Conn, require
from engine.enums import ResolutionMethod
from engine.errors import location_unknown, market_ambiguous, service_unknown

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalise_raw(value: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", value.strip().lower())).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class Resolution:
    market_id: str
    market_key: str
    service: dict[str, Any]
    location: dict[str, Any]
    method: ResolutionMethod
    confidence: float


def _alias_key(service_raw: str, location_raw: str) -> str:
    return f"{normalise_raw(service_raw)}|{normalise_raw(location_raw)}"


def _location_candidates(conn: Conn, raw: str) -> list[tuple[dict[str, Any], float]]:
    rows = conn.execute(
        "SELECT id, slug, display_name, locality, admin1, granularity, population FROM locations"
    ).fetchall()
    scored = []
    for r in rows:
        forms = [
            r["display_name"].lower(),
            (r["locality"] or "").lower(),
            r["slug"].replace("-", " "),
        ]
        if r["locality"] and r["admin1"]:
            forms.append(f"{r['locality']} {r['admin1']}".lower())
        scored.append((r, max(_ratio(raw, f) for f in forms if f)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _get_or_create_market(
    conn: Conn, service_id: int, location_id: int, market_key: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, market_key FROM markets WHERE service_id=%s AND location_id=%s",
        (service_id, location_id),
    ).fetchone()
    if row:
        return row
    return require(
        conn.execute(
            "INSERT INTO markets (service_id, location_id, market_key) VALUES (%s,%s,%s) "
            "RETURNING id, market_key",
            (service_id, location_id, market_key),
        ).fetchone(),
        "inserted market",
    )


def _record_alias(
    conn: Conn, key: str, market_id: str, method: ResolutionMethod, conf: float
) -> None:
    conn.execute(
        """
        INSERT INTO market_aliases (raw_input, market_id, resolution_method, confidence)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (raw_input) DO UPDATE
          SET last_seen_at = now(),
              hit_count = market_aliases.hit_count + 1
        """,
        (key, market_id, method.value, conf),
    )


def _load(conn: Conn, market_id: str) -> dict[str, Any]:
    return require(
        conn.execute(
            """
        SELECT m.id, m.market_key,
               s.slug AS service_slug, s.display_name AS service_name,
               l.slug AS location_slug, l.display_name AS location_name,
               l.granularity, l.population
        FROM markets m
        JOIN services s ON s.id = m.service_id
        JOIN locations l ON l.id = m.location_id
        WHERE m.id = %s
        """,
            (market_id,),
        ).fetchone(),
        "market",
    )


def _resolution_from_row(row: dict[str, Any], method: ResolutionMethod, conf: float) -> Resolution:
    return Resolution(
        market_id=str(row["id"]),
        market_key=row["market_key"],
        service={"slug": row["service_slug"], "display_name": row["service_name"]},
        location={
            "slug": row["location_slug"],
            "display_name": row["location_name"],
            "granularity": row["granularity"],
        },
        method=method,
        confidence=conf,
    )


def _service_candidates(conn: Conn, raw: str) -> list[tuple[dict[str, Any], float]]:
    rows = conn.execute("SELECT id, slug, display_name FROM services WHERE is_active").fetchall()
    scored = [
        (r, max(_ratio(raw, r["slug"].replace("-", " ")), _ratio(raw, r["display_name"].lower())))
        for r in rows
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _candidate_block(
    service: dict[str, Any], location: dict[str, Any], conf: float
) -> dict[str, Any]:
    return {
        "market_key": f"{service['slug']}@{location['slug']}",
        "display_name": f"{service['display_name']} — {location['display_name']}",
        "confidence": round(conf, 3),
    }


def resolve(conn: Conn, service_raw: str, location_raw: str) -> Resolution:
    """Resolve free text to one canonical market, or refuse.

    The confidence gate (`resolution_min_confidence`, documented as 0.75) applies to
    the **combined** confidence of the service and location halves, because a market
    is the pair. A weak match on either half means the pair is not resolved, and the
    caller is asked to choose rather than being handed a guess (02 §3.5, 05 §5.2).
    """
    key = _alias_key(service_raw, location_raw)

    alias = conn.execute(
        "SELECT market_id, confidence FROM market_aliases WHERE raw_input = %s", (key,)
    ).fetchone()
    if alias:
        _record_alias(
            conn, key, alias["market_id"], ResolutionMethod.ALIAS, float(alias["confidence"])
        )
        return _resolution_from_row(
            _load(conn, alias["market_id"]), ResolutionMethod.ALIAS, float(alias["confidence"])
        )

    svc_raw = normalise_raw(service_raw)
    loc_raw = normalise_raw(location_raw)

    services = _service_candidates(conn, svc_raw)
    locations = _location_candidates(conn, loc_raw)

    # Nothing plausible at all -> 422, the input is not in the taxonomy.
    if not services or services[0][1] < settings.resolution_unknown_floor:
        raise service_unknown(service_raw)
    if not locations or locations[0][1] < settings.resolution_unknown_floor:
        raise location_unknown(location_raw)

    # A market is a pair, so its confidence is the weaker of the two halves.
    pairs = [
        (svc, loc, min(svc_conf, loc_conf))
        for svc, svc_conf in services
        for loc, loc_conf in locations
    ]
    pairs.sort(key=lambda x: x[2], reverse=True)

    best_service, best_location, best_conf = pairs[0]
    runner_up_conf = pairs[1][2] if len(pairs) > 1 else 0.0

    too_weak = best_conf < settings.resolution_min_confidence
    too_close = best_conf - runner_up_conf < settings.resolution_ambiguity_margin

    if too_weak or too_close:
        shortlist = [
            _candidate_block(svc, loc, conf)
            for svc, loc, conf in pairs[:4]
            if conf >= settings.resolution_unknown_floor
        ]
        raise market_ambiguous(shortlist, "low_confidence" if too_weak else "too_close")

    market_key = f"{best_service['slug']}@{best_location['slug']}"
    market = _get_or_create_market(conn, best_service["id"], best_location["id"], market_key)
    confidence = round(best_conf, 3)
    method = ResolutionMethod.EXACT if confidence >= 0.999 else ResolutionMethod.FUZZY
    _record_alias(conn, key, market["id"], method, confidence)
    return _resolution_from_row(_load(conn, market["id"]), method, confidence)


def resolve_by_key(conn: Conn, market_key: str) -> Resolution:
    """Resolve an explicit market_key, e.g. one the client picked from a 409 shortlist."""
    row = conn.execute(
        """
        SELECT m.id, m.market_key,
               s.slug AS service_slug, s.display_name AS service_name,
               l.slug AS location_slug, l.display_name AS location_name,
               l.granularity, l.population
        FROM markets m
        JOIN services s ON s.id = m.service_id
        JOIN locations l ON l.id = m.location_id
        WHERE m.market_key = %s
        """,
        (market_key,),
    ).fetchone()
    if row:
        return _resolution_from_row(row, ResolutionMethod.MANUAL, 1.0)

    if "@" not in market_key:
        raise location_unknown(market_key)
    service_slug, _, location_slug = market_key.partition("@")
    service = conn.execute(
        "SELECT id, slug, display_name FROM services WHERE slug = %s AND is_active",
        (service_slug,),
    ).fetchone()
    if not service:
        raise service_unknown(service_slug)
    location = conn.execute(
        "SELECT id, slug FROM locations WHERE slug = %s", (location_slug,)
    ).fetchone()
    if not location:
        raise location_unknown(location_slug)

    market = _get_or_create_market(conn, service["id"], location["id"], market_key)
    return _resolution_from_row(_load(conn, market["id"]), ResolutionMethod.MANUAL, 1.0)
