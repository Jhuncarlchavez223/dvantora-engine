"""App pages served as HTML from the engine process (ADR-0007).

This is a thin view layer. Every route either renders a template or calls the
same shared engine functions the JSON API uses. No business logic belongs here
(docs/08-frontend-integration.md §1.1):

- starting a run goes through engine.pipeline.start.start_run, exactly like
  POST /api/v1/runs;
- reading a run or a report goes through the API's own get_run / get_report,
  so the app can never show a run differently from the API.

The only extra work done here is presentation: turning stored values into
labels a person can read (for example, vendor "fixture" -> "Example data").
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from engine.api.deps import current_account
from engine.api.routes.runs import get_report as api_get_report
from engine.api.routes.runs import get_run as api_get_run
from engine.api.routes.runs import list_runs as api_list_runs
from engine.db import connection
from engine.errors import ApiError
from engine.pipeline.start import start_run

# Folder holding templates/ and static/, resolved relative to this file so it
# works no matter which directory the server is started from.
APP_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=APP_DIR / "templates")

router = APIRouter()

# Plain-English names for the pipeline's stages and statuses. Presentation
# only: the stages themselves are defined by the engine (02 §4).
STAGE_LABELS: dict[str, str] = {
    "resolve": "Market identified",
    "collect_demand": "Demand",
    "collect_competition": "Competition",
    "collect_advertising": "Advertising activity",
    "collect_density": "Business density",
    "collect_value": "Customer value",
    "collect_trends": "Trends",
    "score": "Scoring",
    "analyze": "Written analysis",
    "finalize": "Report",
}

SIGNAL_LABELS: dict[str, str] = {
    "demand": "Demand",
    "competition": "Competition",
    "advertising": "Advertising activity",
    "density": "Business density",
    "customer_value": "Customer value",
    "trends": "Trends",
}

VERDICT_LABELS: dict[str, str] = {"pursue": "Pursue", "watch": "Watch", "pass": "Pass"}

# Where each signal's evidence came from. "fixture" is local example data and
# must always be labelled as such (00 §7). An unknown vendor is shown by name
# rather than assumed to be live.
VENDOR_LABELS: dict[str, str] = {
    "fixture": "Example data",
    "google_ads": "Google Ads",
}

# Statuses for which a report exists (02 §5).
REPORT_STATUSES = {"complete", "partial"}

STATUS_LABELS: dict[str, str] = {
    "queued": "Queued",
    "collecting": "Collecting evidence",
    "scoring": "Scoring",
    "analyzing": "Writing analysis",
    "complete": "Complete",
    "partial": "Complete — some signals unavailable",
    "failed": "Failed — not enough evidence to score",
    "cancelled": "Cancelled",
}


def _render_home(
    request: Request,
    *,
    service: str = "",
    location: str = "",
    error: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "service": service,
            "location": location,
            "error": error,
            "candidates": candidates or [],
        },
        status_code=status_code,
    )


@router.get("/app", response_class=HTMLResponse)
def home(request: Request) -> Response:
    """The new-analysis form."""
    return _render_home(request)


@router.post("/app/runs", response_class=HTMLResponse)
def create_run_from_form(
    request: Request,
    service: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    market_key: Annotated[str, Form()] = "",
) -> Response:
    """Start (or reuse) a run, then send the browser to its page.

    Uses the same shared start_run as the API. It never guesses a market: an
    ambiguous or low-confidence input re-renders the form with a shortlist
    (02 §3.5, 05 §5.2).
    """
    try:
        with connection() as conn:
            account = current_account(conn)
            started = start_run(
                conn,
                account,
                service=service.strip() or None,
                location=location.strip() or None,
                market_key=market_key.strip() or None,
            )
    except ApiError as exc:
        candidates = exc.details.get("candidates", []) if exc.code == "market_ambiguous" else []
        return _render_home(
            request,
            service=service,
            location=location,
            error=exc.message,
            candidates=candidates,
            status_code=exc.status_code,
        )

    # 303 tells the browser to follow up with a GET, so refreshing the next page
    # never re-submits the form.
    target = f"/app/runs/{started.run_id}"
    if started.reused:
        target += "?reused=1"
    return RedirectResponse(target, status_code=303)


@router.get("/app/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str, reused: bool = False) -> Response:
    """Status of one run and its ten stages. Live updating comes next."""
    try:
        uuid.UUID(run_id)
    except ValueError:
        return _render_error(request, "That run doesn't exist.", 404)

    try:
        run = api_get_run(run_id)
    except ApiError as exc:
        return _render_error(request, exc.message, exc.status_code)

    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "run": run,
            "reused": reused,
            "stage_labels": STAGE_LABELS,
            "status_labels": STATUS_LABELS,
            "has_report": run["status"] in REPORT_STATUSES,
        },
    )


def _data_mode(vendors: set[str]) -> str:
    """"example", "mixed" or "live", from the vendors a run actually used."""
    if not vendors or vendors == {"fixture"}:
        return "example"
    if "fixture" in vendors:
        return "mixed"
    return "live"


DATA_MODE_LABELS: dict[str, str] = {
    "example": "Example data",
    "mixed": "Mixed (live + example)",
    "live": "Live",
}


def _report_view(report: dict[str, Any]) -> dict[str, Any]:
    """Add human-readable labels to a stored report. Presentation only."""
    vendors_by_signal: dict[str, list[str]] = {}
    for source in report.get("provenance", {}).get("sources", []):
        vendors_by_signal.setdefault(source["signal"], []).append(source["vendor"])

    signals = []
    used_vendors: set[str] = set()
    for s in report.get("signals", []):
        vendors = sorted(vendors_by_signal.get(s["signal"], []))
        if s["score"] is not None:
            used_vendors.update(vendors)
        signals.append(
            {
                **s,
                "label": SIGNAL_LABELS.get(s["signal"], s["signal"]),
                "source_labels": [VENDOR_LABELS.get(v, v) for v in vendors],
                "is_example": "fixture" in vendors,
            }
        )

    # Is this report built from live data, example data, or a mix? This drives
    # the banner, so nobody mistakes an example-data score for a real one.
    data_mode = _data_mode(used_vendors)

    density_vendors = sorted(vendors_by_signal.get("density", []))
    return {
        "signals": signals,
        "data_mode": data_mode,
        "available_count": sum(1 for s in signals if s["score"] is not None),
        "density_source_labels": [VENDOR_LABELS.get(v, v) for v in density_vendors],
        "verdict_label": VERDICT_LABELS.get(report["score"]["verdict"], report["score"]["verdict"]),
    }


@router.get("/app/runs/{run_id}/report", response_class=HTMLResponse)
def report_page(request: Request, run_id: str) -> Response:
    """The finished report. Sends the browser back to the run page until ready."""
    try:
        uuid.UUID(run_id)
    except ValueError:
        return _render_error(request, "That run doesn't exist.", 404)

    try:
        report = api_get_report(run_id)
    except ApiError as exc:
        if exc.code == "report_not_ready":
            return RedirectResponse(f"/app/runs/{run_id}", status_code=303)
        return _render_error(request, exc.message, exc.status_code)

    return templates.TemplateResponse(
        request,
        "report.html",
        {"report": report, "view": _report_view(report)},
    )


def _render_error(request: Request, message: str, status_code: int) -> Response:
    return templates.TemplateResponse(
        request, "error.html", {"message": message}, status_code=status_code
    )


@router.get("/app/markets", response_class=HTMLResponse)
def markets_page(request: Request) -> Response:
    """Past runs, newest first, each labelled with where its data came from."""
    listing = api_list_runs(limit=50)
    runs = []
    for item in listing["items"]:
        finished = item["status"] in REPORT_STATUSES
        mode = _data_mode(set(item["data_sources"])) if finished else None
        runs.append(
            {
                **item,
                "status_label": STATUS_LABELS.get(item["status"], item["status"]),
                "verdict_label": VERDICT_LABELS.get(item["verdict"] or "", ""),
                # Only label data for finished runs; others have no report yet.
                "data_label": DATA_MODE_LABELS[mode] if mode else "",
                "is_example": mode in ("example", "mixed"),
                "href": (
                    f"/app/runs/{item['run_id']}/report"
                    if finished
                    else f"/app/runs/{item['run_id']}"
                ),
            }
        )
    return templates.TemplateResponse(request, "markets.html", {"runs": runs})
