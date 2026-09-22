"""App pages served as HTML from the engine process (ADR-0007).

This is a thin view layer. Every route either renders a template or calls the
same shared engine functions the JSON API uses. No business logic belongs here
(docs/08-frontend-integration.md §1.1).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Folder holding templates/ and static/, resolved relative to this file so it
# works no matter which directory the server is started from.
APP_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=APP_DIR / "templates")

router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Landing page of the app. The analysis form arrives in the next step."""
    return templates.TemplateResponse(request, "index.html", {})
