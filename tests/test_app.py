"""Server-rendered app pages (ADR-0007). No vendor calls, no model calls."""

from __future__ import annotations


def test_app_home_renders_html(client):
    response = client.get("/app")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Dvantora" in response.text
    # The page must link the app's own stylesheet, not the marketing site's.
    assert "/app/static/main.css" in response.text


def test_app_stylesheet_is_served(client):
    response = client.get("/app/static/main.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    # Design tokens copied from the marketing site are present.
    assert "--accent" in response.text
