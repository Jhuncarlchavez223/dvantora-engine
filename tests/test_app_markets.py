"""Past-research list (/app/markets). Fixture mode; no vendor or model calls."""

from __future__ import annotations

from engine import db
from engine.pipeline import queue
from engine.pipeline.worker import execute_run

PLUMBING = {"service": "Plumbing", "location": "Brisbane, QLD"}


def _drain() -> None:
    while True:
        with db.connection() as conn:
            claimed = queue.claim_next(conn, "worker-test")
            conn.commit()
        if claimed is None:
            return
        with db.connection() as conn:
            execute_run(conn, str(claimed["id"]))


def test_empty_list_says_so(client):
    html = client.get("/app/markets").text
    assert "No research yet" in html


def test_finished_run_is_listed_with_its_data_source(client):
    run_id = client.post("/api/v1/runs", json=PLUMBING).json()["run_id"]
    _drain()
    html = client.get("/app/markets").text
    assert "Plumbing — Brisbane, QLD" in html
    assert f"/app/runs/{run_id}/report" in html  # finished runs link to the report
    assert "Example data" in html  # fixture runs are never shown as live


def test_unfinished_run_links_to_its_run_page(client):
    run_id = client.post("/api/v1/runs", json=PLUMBING).json()["run_id"]  # queued
    html = client.get("/app/markets").text
    assert f'href="/app/runs/{run_id}"' in html
    assert "Queued" in html


def test_api_list_reports_data_sources(client):
    client.post("/api/v1/runs", json=PLUMBING)
    _drain()
    item = client.get("/api/v1/runs").json()["items"][0]
    assert item["data_sources"] == ["fixture"]
    assert item["requested_at"]


def test_nav_links_to_past_research(client):
    assert 'href="/app/markets"' in client.get("/app").text
