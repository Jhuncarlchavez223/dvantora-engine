"""Server-rendered app pages (ADR-0007).

These tests use fixture mode (forced in conftest.py). Starting a run only queues
it; no worker runs here, so no vendor or model is ever called.
"""

from __future__ import annotations

import uuid

PLUMBING = {"service": "Plumbing", "location": "Brisbane, QLD"}


def test_app_home_renders_html(client):
    response = client.get("/app")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Dvantora" in response.text
    # The page links the app's own stylesheets, not the marketing site's.
    assert "/app/static/main.css" in response.text
    assert "/app/static/app.css" in response.text


def test_app_stylesheets_are_served(client):
    main = client.get("/app/static/main.css")
    assert main.status_code == 200
    assert main.headers["content-type"].startswith("text/css")
    assert "--accent" in main.text  # design tokens copied from the website

    app_css = client.get("/app/static/app.css")
    assert app_css.status_code == 200
    assert ".dv-form" in app_css.text


def test_home_has_the_analysis_form(client):
    html = client.get("/app").text
    assert 'action="/app/runs"' in html
    assert 'name="service"' in html
    assert 'name="location"' in html


def test_submitting_the_form_queues_a_run_and_redirects(client):
    response = client.post("/app/runs", data=PLUMBING, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/app/runs/")

    page = client.get(location)
    assert page.status_code == 200
    assert "Plumbing — Brisbane, QLD" in page.text
    assert "Queued" in page.text
    assert "Demand" in page.text  # a stage label rendered


def test_form_and_api_start_runs_the_same_way(client):
    """The boundary rule (08 §1.1): both surfaces share start_run."""
    api = client.post("/api/v1/runs", json=PLUMBING)
    assert api.status_code == 202

    # The same market is now active, so the form must not queue a second run.
    form = client.post("/app/runs", data=PLUMBING, follow_redirects=False)
    assert form.status_code == 409
    assert "already active" in form.text


def test_ambiguous_market_shows_choices_instead_of_guessing(client):
    response = client.post(
        "/app/runs", data={"service": "Plumbing", "location": "Richmond"}
    )
    assert response.status_code == 409
    assert "Richmond, VIC" in response.text
    assert "Richmond, NSW" in response.text
    # Each choice re-submits an explicit market_key.
    assert 'name="market_key" value="plumbing@au-vic-richmond"' in response.text


def test_choosing_a_candidate_starts_that_market(client):
    response = client.post(
        "/app/runs",
        data={"market_key": "plumbing@au-vic-richmond"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert "Plumbing — Richmond, VIC" in page.text


def test_unknown_service_shows_an_error_and_keeps_the_input(client):
    response = client.post(
        "/app/runs", data={"service": "quantum tarot reading", "location": "Brisbane, QLD"}
    )
    assert response.status_code == 422
    assert 'role="alert"' in response.text
    assert 'value="quantum tarot reading"' in response.text  # user's input kept


def test_unknown_run_is_a_404_page(client):
    assert client.get(f"/app/runs/{uuid.uuid4()}").status_code == 404
    assert client.get("/app/runs/not-a-uuid").status_code == 404
