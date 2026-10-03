"""Tests for the /api/exports/* endpoints (Step 25 — exports & reporting).

Each export derives from the in-memory run stores, so we first create a run
(which simulates the hardcoded demo design) and then export its artifacts.
"""

import json
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from agentarium.app import app

client = TestClient(app)


def _make_run() -> str:
    r = client.post("/api/runs", json={"duration_seconds": 1.0})
    assert r.status_code == 200
    return r.json()["run_id"]


def test_export_design_yaml():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/design")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "bodies:" in r.text  # YAML body of the design


def test_export_design_json():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/design", params={"format": "json"})
    assert r.status_code == 200
    data = json.loads(r.text)
    assert "bodies" in data
    assert isinstance(data["bodies"], list)


def test_export_design_bad_format_rejected():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/design", params={"format": "xml"})
    assert r.status_code == 422  # pattern constraint rejects it


def test_export_trace_jsonl():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/trace")
    assert r.status_code == 200
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    # Header line + at least one frame line, each valid JSON.
    assert len(lines) >= 2
    header = json.loads(lines[0])
    assert header["run_id"] == run_id
    frame = json.loads(lines[1])
    assert "bodies" in frame


def test_export_scorecard_json():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/scorecard")
    assert r.status_code == 200
    data = json.loads(r.text)
    assert "score_total" in data
    assert "metrics" in data


def test_export_report_markdown():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/report")
    assert r.status_code == 200
    body = r.text
    assert body.startswith("# AgentGymnasium Run Report")
    assert "## Score" in body
    assert "## Metrics" in body
    assert "## Design" in body
    assert run_id in body


def test_export_package_zip():
    run_id = _make_run()
    r = client.get(f"/api/exports/{run_id}/package")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert {
            "report.md",
            "design.yaml",
            "trace.json",
            "trace.jsonl",
            "score.json",
            "build_snapshots.json",
        } <= names
        assert json.loads(zf.read("build_snapshots.json").decode("utf-8")) == []


def test_export_unknown_run_404():
    for path in ("design", "trace", "scorecard", "report", "package"):
        r = client.get(f"/api/exports/does-not-exist/{path}")
        assert r.status_code == 404
