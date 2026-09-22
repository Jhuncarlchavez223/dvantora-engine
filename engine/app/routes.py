"""App pages served as HTML from the engine process (ADR-0007).

This is a thin view layer. Every route either renders a template or calls the
same shared engine functions the JSON API uses. No business logic belongs here
(docs/08-frontend-integration.md §1.1):

- starting a run goes through engine.pipeline.start.start_run, exactly like
  POST /api/v1/runs;
- reading a run goes through the API's own get_run, so the app can never show
  a run differently from the API.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from engine.api.deps import current_account
from engine.api.routes.runs import get_run as api_get_run
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
        },
    )


def _render_error(request: Request, message: str, status_code: int) -> Response:
    return templates.TemplateResponse(
        request, "error.html", {"message": message}, status_code=status_code
    )
