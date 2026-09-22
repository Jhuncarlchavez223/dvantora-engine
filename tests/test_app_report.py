"""The server-rendered report page (ADR-0007, 08 §5).

Fixture mode only (forced in conftest.py). Runs are executed in-process by the
same code the worker uses, so no vendor or model is ever called.
"""

from __future__ import annotations

import uuid

from engine import db
from engine.pipeline import queue
from engine.pipeline.worker import execute_run

PLUMBING = {"service": "Plumbing", "location": "Brisbane, QLD"}
ELECTRICAL = {"service": "Electrical", "location": "Brisbane, QLD"}


def _drain() -> None:
    """Process every queued run, as the worker process would."""
    while True:
        with db.connection() as conn:
            claimed = queue.claim_next(conn, "worker-test")
            conn.commit()
        if claimed is None:
            return
        with db.connection() as conn:
            execute_run(conn, str(claimed["id"]))


def _completed_run(client, market: dict[str, str]) -> str:
    run_id = client.post("/api/v1/runs", json=market).json()["run_id"]
    _drain()
    return run_id


def test_report_page_shows_score_verdict_and_all_six_signals(client):
    run_id = _completed_run(client, PLUMBING)
    api_report = client.get(f"/api/v1/runs/{run_id}/report").json()

    page = client.get(f"/app/runs/{run_id}/report")
    assert page.status_code == 200
    html = page.text

    # The displayed score is the exact stored value the verdict was decided from.
    assert f'{api_report["score"]["opportunity_score"]:.2f}' in html
    verdict = api_report["score"]["verdict"].capitalize()
    assert verdict in html

    for name in (
        "Demand",
        "Competition",
        "Advertising activity",
        "Business density",
        "Customer value",
        "Trends",
    ):
        assert name in html


def test_example_data_is_always_labelled(client):
    """Fixture evidence must never pass as a real measurement (00 §7)."""
    run_id = _completed_run(client, PLUMBING)
    html = client.get(f"/app/runs/{run_id}/report").text
    assert "Example data only" in html
    assert "not a real measurement" in html
    assert "Example data" in html  # per-signal source label


def test_unavailable_signal_is_shown_not_hidden(client):
    """05 §6.1 rule 1: a missing signal is shown as unavailable, never omitted."""
    run_id = _completed_run(client, ELECTRICAL)  # its advertising fixture fails
    html = client.get(f"/app/runs/{run_id}/report").text
    assert "Advertising activity" in html
    assert "Unavailable" in html


def test_report_does_not_show_unsourced_advertising_flags(client):
    """The fixture has per-business 'advertising' flags with no live source."""
    run_id = _completed_run(client, PLUMBING)
    html = client.get(f"/app/runs/{run_id}/report").text
    assert "share_advertising" not in html
    assert "share_with_website" not in html


def test_run_page_links_to_report_when_complete(client):
    run_id = _completed_run(client, PLUMBING)
    html = client.get(f"/app/runs/{run_id}").text
    assert f"/app/runs/{run_id}/report" in html
    assert "View report" in html


def test_report_before_completion_redirects_to_run_page(client):
    run_id = client.post("/api/v1/runs", json=PLUMBING).json()["run_id"]  # queued only
    response = client.get(f"/app/runs/{run_id}/report", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/app/runs/{run_id}"


def test_unknown_report_is_a_404_page(client):
    assert client.get(f"/app/runs/{uuid.uuid4()}/report").status_code == 404
    assert client.get("/app/runs/not-a-uuid/report").status_code == 404


def test_unfinished_run_page_refreshes_itself(client):
    run_id = client.post("/api/v1/runs", json=PLUMBING).json()["run_id"]  # queued only
    html = client.get(f"/app/runs/{run_id}").text
    assert 'http-equiv="refresh"' in html


def test_finished_run_page_stops_refreshing(client):
    run_id = _completed_run(client, PLUMBING)
    html = client.get(f"/app/runs/{run_id}").text
    assert 'http-equiv="refresh"' not in html
    assert "View report" in html
