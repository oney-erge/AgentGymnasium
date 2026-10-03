"""The built web UI is committed and served (Step 25.5 — no-Node launch).

These guard against the bundle silently going missing, which would break the
one-command launch for users who don't have Node.
"""

import pathlib

from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)


def test_static_bundle_is_committed():
    static = (
        pathlib.Path(__file__).resolve().parents[1]
        / "agentgymnasium"
        / "static"
        / "index.html"
    )
    assert static.is_file(), "built web UI must be committed at agentgymnasium/static/index.html"


def test_root_serves_spa_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_api_still_routes_under_spa_fallback():
    # The SPA catch-all must not shadow API routes.
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
