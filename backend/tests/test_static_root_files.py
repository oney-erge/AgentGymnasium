"""Root static assets (favicon, icons) are served as themselves, not index.html.

Regression guard: the SPA catch-all must serve real files that live in the
static root (referenced by index.html) instead of shadowing them with the
HTML shell.
"""
from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)


def test_favicon_served_as_svg_not_html():
    r = client.get("/favicon.svg")
    assert r.status_code == 200
    ctype = r.headers.get("content-type", "")
    # Must be an SVG/image type, not the HTML shell.
    assert "svg" in ctype or "image" in ctype
    assert "<!doctype html" not in r.text.lower()


def test_unknown_route_still_returns_spa_html():
    r = client.get("/studio/some-run-id")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_path_traversal_falls_back_to_index():
    # A traversal attempt must not escape the static root; it returns the SPA.
    r = client.get("/../../etc/passwd")
    assert r.status_code in (200, 404)
    assert "root:" not in r.text
