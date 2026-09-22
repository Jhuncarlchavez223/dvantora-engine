"""ADR-0005 freshness reuse must respect where a run's data came from.

A recent run built from example (fixture) data must not be reused when the
engine currently collects a signal live. These tests run in fixture mode and
never execute a live collector: live sources are simulated by monkeypatching
or by relabelling evidence in the separate test database.
"""

from __future__ import annotations

from engine import db
from engine.collectors import live_sources
from engine.config import settings
from engine.pipeline import queue
from engine.pipeline.worker import execute_run

PLUMBING = {"service": "Plumbing", "location": "Brisbane, QLD"}


def _drain() -> None:
    """Process every queued run in fixture mode, as the worker would."""
    while True:
        with db.connection() as conn:
            claimed = queue.claim_next(conn, "worker-test")
            conn.commit()
        if claimed is None:
            return
        with db.connection() as conn:
            execute_run(conn, str(claimed["id"]))


def _fixture_run(client) -> tuple[str, str]:
    """A completed all-fixture Plumbing — Brisbane run: (run_id, market_id)."""
    run_id = client.post("/api/v1/runs", json=PLUMBING).json()["run_id"]
    _drain()
    with db.connection() as conn:
        row = conn.execute(
            "SELECT market_id FROM research_runs WHERE id = %s", (run_id,)
        ).fetchone()
    assert row is not None
    return run_id, str(row["market_id"])


def test_live_sources_is_empty_in_fixture_mode():
    assert live_sources() == {}


def test_live_sources_names_google_ads_demand_in_hybrid_mode(monkeypatch):
    # Only reads the collector list; no collector is run, so nothing calls Google.
    monkeypatch.setattr(settings, "collector_mode", "hybrid")
    assert live_sources() == {"demand": "google_ads"}


def test_fixture_run_is_reused_when_nothing_is_expected_live(client):
    run_id, market_id = _fixture_run(client)
    with db.connection() as conn:
        fresh = queue.find_fresh_run(conn, market_id, {})
    assert fresh is not None
    assert str(fresh["id"]) == run_id


def test_fixture_run_is_not_reused_when_demand_is_expected_live(client):
    _, market_id = _fixture_run(client)
    with db.connection() as conn:
        fresh = queue.find_fresh_run(conn, market_id, {"demand": "google_ads"})
    assert fresh is None


def test_run_with_matching_live_source_is_reused(client):
    run_id, market_id = _fixture_run(client)
    with db.connection() as conn:
        # Simulate a run whose Demand evidence really came from Google Ads.
        conn.execute(
            "UPDATE evidence SET vendor = 'google_ads' WHERE run_id = %s AND signal = 'demand'",
            (run_id,),
        )
        conn.commit()
        fresh = queue.find_fresh_run(conn, market_id, {"demand": "google_ads"})
    assert fresh is not None
    assert str(fresh["id"]) == run_id


def test_start_run_queues_a_new_run_instead_of_reusing_example_data(client, monkeypatch):
    fixture_run_id, _ = _fixture_run(client)

    # Pretend the engine now collects Demand live. The new run is only queued,
    # never processed here, so no live collector runs.
    monkeypatch.setattr("engine.pipeline.start.live_sources", lambda: {"demand": "google_ads"})

    response = client.post("/api/v1/runs", json=PLUMBING)
    assert response.status_code == 202
    body = response.json()
    assert body["reused"] is False
    assert body["run_id"] != fixture_run_id
