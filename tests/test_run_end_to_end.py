"""The walking skeleton's definition of done.

A market goes from typed text to a stored, scored, explained report using only
local fixtures — no vendor calls, no model calls.
"""

from __future__ import annotations

from engine import db
from engine.pipeline import queue
from engine.pipeline.worker import execute_run

PLUMBING = {"service": "Plumbing", "location": "Brisbane, QLD"}
ELECTRICAL = {"service": "Electrical", "location": "Brisbane, QLD"}
RICHMOND = {"market_key": "plumbing@au-vic-richmond"}


def _drain(worker_id: str = "worker-test") -> list[str]:
    """Claim and execute every queued run, as the worker process would."""
    finished = []
    while True:
        with db.connection() as conn:
            claimed = queue.claim_next(conn, worker_id)
            conn.commit()
        if claimed is None:
            return finished
        with db.connection() as conn:
            finished.append(execute_run(conn, str(claimed["id"])))


def test_complete_run_produces_a_scored_report(client):
    created = client.post("/api/v1/runs", json=PLUMBING)
    assert created.status_code == 202, created.text
    body = created.json()
    run_id = body["run_id"]
    assert body["reused"] is False
    assert body["market"]["market_key"] == "plumbing@au-qld-brisbane"
    assert body["poll_after_ms"] == 3000

    # Report is not available while the run is queued (05 §6).
    early = client.get(f"/api/v1/runs/{run_id}/report")
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "report_not_ready"

    assert _drain() == ["complete"]

    status = client.get(f"/api/v1/runs/{run_id}").json()
    assert status["status"] == "complete"
    assert status["poll_after_ms"] is None
    assert status["progress"]["completed"] == status["progress"]["total"] == 10
    assert [s["stage"] for s in status["stages"]][:2] == ["resolve", "collect_demand"]
    assert all(s["status"] == "ok" for s in status["stages"])

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["schema_version"] == "1"
    assert 0 <= report["score"]["opportunity_score"] <= 100
    assert report["score"]["verdict"] in {"pursue", "watch", "pass"}
    assert len(report["signals"]) == 6  # all six, always
    assert all(s["score"] is not None for s in report["signals"])
    assert report["analysis"]["generator"] == "template"  # no LLM (ADR-0004)
    assert report["provenance"]["weights_version"] == "1.0"
    assert report["provenance"]["gates_applied"] == []  # nothing capped this verdict
    assert report["businesses"]["available"] is True
    assert report["businesses"]["expires_at"] is not None  # 30-day TTL (02 §6)
    assert report["businesses"]["aggregates"]["business_count"] == 128


def test_freshness_window_reuses_the_run(client):
    first = client.post("/api/v1/runs", json=PLUMBING).json()
    _drain()

    second = client.post("/api/v1/runs", json=PLUMBING)
    assert second.status_code == 200
    body = second.json()
    assert body["reused"] is True
    assert body["run_id"] == first["run_id"]
    assert body["freshness_window_hours"] == 168
    assert body["data_age_hours"] >= 0


def test_force_refresh_bypasses_the_window(client):
    first = client.post("/api/v1/runs", json=PLUMBING).json()
    _drain()
    forced = client.post("/api/v1/runs", json={**PLUMBING, "force_refresh": True})
    assert forced.status_code == 202
    assert forced.json()["run_id"] != first["run_id"]


def test_failed_collector_yields_partial_not_failure(client):
    created = client.post("/api/v1/runs", json=ELECTRICAL)
    assert created.status_code == 202
    run_id = created.json()["run_id"]

    assert _drain() == ["partial"]

    status = client.get(f"/api/v1/runs/{run_id}").json()
    assert status["status"] == "partial"
    advertising = next(s for s in status["stages"] if s["stage"] == "collect_advertising")
    assert advertising["status"] == "failed"
    assert advertising["error_code"] == "vendor_unavailable"

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert len(report["signals"]) == 6
    missing = next(s for s in report["signals"] if s["signal"] == "advertising")
    assert missing["score"] is None  # present with null, never omitted (05 §6.1)
    assert missing["band"] == "unknown"
    assert "unavailable" in (missing["notes"] or "")
    assert any("advertising" in c.lower() for c in report["analysis"]["caveats"])
    assert report["score"]["opportunity_score"] is not None
    assert report["provenance"]["coverage"] < 1.0
    # Advertising is absent but customer value is present, so G3 must NOT fire (04 §6).
    assert "G3_no_monetisation_evidence" not in report["provenance"]["gates_applied"]


def test_insufficient_evidence_fails_without_inventing_a_score(client):
    created = client.post("/api/v1/runs", json=RICHMOND)
    assert created.status_code == 202
    run_id = created.json()["run_id"]

    assert _drain() == ["failed"]

    status = client.get(f"/api/v1/runs/{run_id}").json()
    assert status["status"] == "failed"
    assert status["error_code"] == "insufficient_evidence"

    report = client.get(f"/api/v1/runs/{run_id}/report")
    assert report.status_code == 409

    with db.connection() as conn:
        rows = conn.execute(
            "SELECT count(*) AS c FROM scores WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert rows["c"] == 0


def test_evidence_endpoint_exposes_provenance(client):
    run_id = client.post("/api/v1/runs", json=PLUMBING).json()["run_id"]
    _drain()
    ev = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert ev["items"]
    assert {i["vendor"] for i in ev["items"]} == {"fixture"}
    density = [i for i in ev["items"] if i["signal"] == "density"]
    assert any(i["expires_at"] is not None for i in density)  # identity rows expire
    assert any(i["expires_at"] is None for i in density)  # aggregates do not


def test_outbox_event_written_without_any_webhook_configured(client):
    client.post("/api/v1/runs", json=PLUMBING)
    _drain()
    with db.connection() as conn:
        row = conn.execute(
            "SELECT event_type, delivered_at FROM events_outbox ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["event_type"] == "run.completed"
    assert row["delivered_at"] is None  # ADR-0006: nothing delivers, nothing breaks


def test_ambiguous_market_returns_candidates(client):
    r = client.post("/api/v1/runs", json={"service": "Plumbing", "location": "Richmond"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "market_ambiguous"
    assert len(err["details"]["candidates"]) >= 2


def test_run_list_and_market_history(client):
    client.post("/api/v1/runs", json=PLUMBING)
    _drain()
    listed = client.get("/api/v1/runs").json()
    assert listed["items"][0]["verdict"] in {"pursue", "watch", "pass"}
    history = client.get("/api/v1/markets/plumbing@au-qld-brisbane/runs").json()
    assert len(history["items"]) == 1


def test_health_and_services(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    slugs = {s["slug"] for s in client.get("/api/v1/services").json()["items"]}
    assert {"plumbing", "electrical"} <= slugs


def test_declining_market_verdict_is_capped_and_explained(client):
    """electrical@au-qld-brisbane has a declining trend fixture (04 §6, G4)."""
    run_id = client.post("/api/v1/runs", json=ELECTRICAL).json()["run_id"]
    assert _drain() == ["partial"]

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    trends = next(s for s in report["signals"] if s["signal"] == "trends")
    assert trends["band"] == "declining"
    assert "G4_declining_trend" in report["provenance"]["gates_applied"]
    assert report["score"]["verdict"] in {"watch", "pass"}
    assert any("declining" in c.lower() for c in report["analysis"]["caveats"])


def test_trend_granularity_is_disclosed_in_the_report(client):
    """The electrical fixture is measured at state level (07 §7.1)."""
    run_id = client.post("/api/v1/runs", json=ELECTRICAL).json()["run_id"]
    _drain()
    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["trend"]["granularity"] == "admin1"
    assert "coarser than the market" in (report["trend"]["note"] or "")
