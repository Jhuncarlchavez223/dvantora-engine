"""02 §3.6 — the queue is Postgres. SKIP LOCKED must hand a run to one worker only."""

from __future__ import annotations

import pytest

from engine import db
from engine.errors import ApiError
from engine.markets import resolver
from engine.pipeline import queue


def _market(conn) -> str:
    res = resolver.resolve(conn, "Plumbing", "Brisbane, QLD")
    conn.commit()
    return res.market_id


def test_enqueue_then_claim(conn):
    market_id = _market(conn)
    run = queue.enqueue(conn, market_id, None)
    conn.commit()
    claimed = queue.claim_next(conn, "worker-test")
    conn.commit()
    assert claimed is not None
    assert str(claimed["id"]) == str(run["id"])
    assert claimed["status"] == "collecting"
    assert claimed["attempt"] == 1


def test_second_active_run_for_same_market_rejected(conn):
    market_id = _market(conn)
    queue.enqueue(conn, market_id, None)
    conn.commit()
    with pytest.raises(ApiError) as exc:
        queue.enqueue(conn, market_id, None)
    assert exc.value.code == "run_in_progress"
    conn.rollback()


def test_skip_locked_gives_the_run_to_exactly_one_worker(conn):
    market_id = _market(conn)
    queue.enqueue(conn, market_id, None)
    conn.commit()

    with db.connection() as c1, db.connection() as c2:
        first = queue.claim_next(c1, "worker-1")
        second = queue.claim_next(c2, "worker-2")
        assert first is not None
        assert second is None  # the row is locked, not duplicated
        c1.commit()
        c2.commit()


def test_reaper_requeues_a_stranded_run(conn):
    market_id = _market(conn)
    run = queue.enqueue(conn, market_id, None)
    conn.commit()
    queue.claim_next(conn, "worker-dead")
    conn.execute(
        "UPDATE research_runs SET claimed_at = now() - interval '2 hours' WHERE id=%s",
        (run["id"],),
    )
    conn.commit()
    assert queue.reap_stuck(conn) == 1
    conn.commit()
    row = conn.execute("SELECT status FROM research_runs WHERE id=%s", (run["id"],)).fetchone()
    assert row["status"] == "queued"
