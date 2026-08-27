"""02 §3.5 / 05 §5 — resolution must be canonical and must refuse to guess."""

from __future__ import annotations

import pytest

from engine.errors import ApiError
from engine.markets import resolver


def test_variants_resolve_to_one_market(conn):
    a = resolver.resolve(conn, "Plumbing", "Brisbane, QLD")
    b = resolver.resolve(conn, "plumbing", "brisbane qld")
    c = resolver.resolve(conn, "Plumbing", "Brisbane — QLD")
    conn.commit()
    assert a.market_key == b.market_key == c.market_key == "plumbing@au-qld-brisbane"


def test_alias_is_recorded_and_reused(conn):
    resolver.resolve(conn, "Plumbing", "Brisbane, QLD")
    conn.commit()
    row = conn.execute(
        "SELECT hit_count FROM market_aliases WHERE raw_input = %s", ("plumbing|brisbane qld",)
    ).fetchone()
    assert row["hit_count"] == 1
    resolver.resolve(conn, "Plumbing", "Brisbane QLD")
    conn.commit()
    row = conn.execute(
        "SELECT hit_count FROM market_aliases WHERE raw_input = %s", ("plumbing|brisbane qld",)
    ).fetchone()
    assert row["hit_count"] == 2


def test_ambiguous_location_raises_409_with_candidates(conn):
    with pytest.raises(ApiError) as exc:
        resolver.resolve(conn, "Plumbing", "Richmond")
    assert exc.value.status_code == 409
    assert exc.value.code == "market_ambiguous"
    keys = {c["market_key"] for c in exc.value.details["candidates"]}
    assert "plumbing@au-vic-richmond" in keys
    assert "plumbing@au-nsw-richmond" in keys


def test_unknown_service_rejected(conn):
    with pytest.raises(ApiError) as exc:
        resolver.resolve(conn, "quantum tarot reading", "Brisbane, QLD")
    assert exc.value.code == "service_unknown"


def test_unknown_location_rejected(conn):
    with pytest.raises(ApiError) as exc:
        resolver.resolve(conn, "Plumbing", "Ulaanbaatar")
    assert exc.value.code == "location_unknown"


def test_weak_service_match_is_not_accepted(conn):
    """The 0.75 gate applies to the combined pair, not the location half alone.

    "plumber" matches "plumbing" at ~0.67. That is below the documented threshold,
    so the market must not resolve — it previously did, because the gate was only
    applied to the location.
    """
    with pytest.raises(ApiError) as exc:
        resolver.resolve(conn, "plumber", "Brisbane, QLD")
    assert exc.value.status_code == 409
    assert exc.value.code == "market_ambiguous"
    candidates = exc.value.details["candidates"]
    assert candidates, "a low-confidence refusal must still offer a shortlist"
    assert all(c["confidence"] < 0.75 for c in candidates)
    assert "plumbing@au-qld-brisbane" in {c["market_key"] for c in candidates}


def test_no_alias_is_recorded_for_a_refused_resolution(conn):
    with pytest.raises(ApiError):
        resolver.resolve(conn, "plumber", "Brisbane, QLD")
    row = conn.execute("SELECT count(*) AS c FROM market_aliases").fetchone()
    assert row["c"] == 0


def test_accepted_resolution_confidence_clears_the_threshold(conn):
    res = resolver.resolve(conn, "Plumbing", "Brisbane, QLD")
    conn.commit()
    assert res.confidence >= 0.75


def test_client_can_recover_from_a_409_using_a_candidate_key(conn):
    with pytest.raises(ApiError) as exc:
        resolver.resolve(conn, "plumber", "Brisbane, QLD")
    chosen = next(
        c for c in exc.value.details["candidates"] if c["market_key"] == "plumbing@au-qld-brisbane"
    )
    res = resolver.resolve_by_key(conn, chosen["market_key"])
    conn.commit()
    assert res.market_key == "plumbing@au-qld-brisbane"
    assert res.method.value == "manual"
