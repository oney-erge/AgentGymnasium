"""Export service: serialize a run's artifacts for download.

Every export is derived from the in-memory stores in
:mod:`agentgymnasium.services.run_service` (trace, scorecard, design) keyed by a
``run_id`` (a trace_run_id). Functions return ``None`` when the run is unknown
so routers can map that to a 404.

The Markdown report is self-contained: it embeds the objective, the scorecard,
the metric breakdown and the design part counts so a reader needs no other file.
"""

from __future__ import annotations

import json
import pathlib
import zipfile
from io import BytesIO

import yaml

from agentgymnasium.core.schemas.design import DesignSpec
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.services.run_service import get_design, get_score, get_trace

_RUNS_DIR = pathlib.Path("runs")


def export_design(run_id: str, fmt: str = "yaml") -> str | None:
    """Serialize the design behind ``run_id`` as YAML (default) or JSON."""
    design = get_design(run_id)
    if design is None:
        return None
    data = design.model_dump(mode="json")
    if fmt == "json":
        return json.dumps(data, indent=2)
    return yaml.safe_dump(data, sort_keys=False)


def export_trace(run_id: str, fmt: str = "jsonl") -> str | None:
    """Serialize the trace as JSONL (one frame per line) or a single JSON doc."""
    trace = get_trace(run_id)
    if trace is None:
        return None
    if fmt == "json":
        return trace.model_dump_json(indent=2)
    # JSONL: a header line with run metadata, then one line per frame.
    lines = [
        json.dumps(
            {
                "run_id": trace.run_id,
                "engine": trace.engine,
                "dt": trace.dt,
                "world_static": [p.model_dump(mode="json") for p in trace.world_static],
            }
        )
    ]
    lines.extend(json.dumps(frame.model_dump(mode="json")) for frame in trace.frames)
    return "\n".join(lines) + "\n"


def export_scorecard(run_id: str) -> str | None:
    """Serialize the scorecard for ``run_id`` as pretty JSON."""
    score = get_score(run_id)
    if score is None:
        return None
    return score.model_dump_json(indent=2)


def _part_counts(design: DesignSpec) -> dict[str, int]:
    bodies = len(design.bodies)
    joints = len(design.joints)
    motors = sum(1 for j in design.joints if j.motor_rate is not None)
    return {"bodies": bodies, "joints": joints, "motors": motors}


def _metric_rows(score: ScoreCard) -> str:
    if not score.metrics:
        return "_No metrics recorded._"
    rows = ["| Metric | Value |", "| --- | --- |"]
    for key in sorted(score.metrics):
        rows.append(f"| {key} | {score.metrics[key]:.3f} |")
    return "\n".join(rows)


def export_report(run_id: str) -> str | None:
    """Build a self-contained Markdown run report, or None if the run is unknown."""
    trace = get_trace(run_id)
    score = get_score(run_id)
    if trace is None or score is None:
        return None

    design = get_design(run_id)
    parts = _part_counts(design) if design is not None else {}
    outcome = "✅ Success" if score.success else "❌ Did not meet success criteria"
    duration = trace.frames[-1].t if trace.frames else 0.0

    lines = [
        f"# AgentGymnasium Run Report — `{run_id}`",
        "",
        f"**Outcome:** {outcome}",
        "",
        "## Score",
        "",
        f"- **Total:** {score.score_total:.2f}",
        f"- **Reward:** `{score.reward}`",
        f"- **Summary:** {score.summary or '—'}",
        f"- **Improvement hint:** {score.improvement_hint or '—'}",
        "",
        "## Metrics",
        "",
        _metric_rows(score),
        "",
        "## Design",
        "",
        f"- **Name:** {design.name if design is not None else '—'}",
        f"- **Bodies:** {parts.get('bodies', 0)}",
        f"- **Joints:** {parts.get('joints', 0)}",
        f"- **Motors:** {parts.get('motors', 0)}",
        "",
        "## Simulation",
        "",
        f"- **Engine:** `{trace.engine}`",
        f"- **Timestep (dt):** {trace.dt}",
        f"- **Frames:** {len(trace.frames)}",
        f"- **Duration:** {duration:.2f}s",
        "",
    ]
    if score.failure_events:
        lines.append("## Failure events")
        lines.append("")
        for event in score.failure_events:
            lines.append(f"- `{json.dumps(event)}`")
        lines.append("")
    return "\n".join(lines)


def export_package(run_id: str) -> bytes | None:
    """Build a zip of backend-persisted artifacts for a run."""
    if get_trace(run_id) is None:
        return None

    package = BytesIO()
    run_dir = _RUNS_DIR / run_id
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        report = export_report(run_id)
        if report is not None:
            zf.writestr("report.md", report)
        design = export_design(run_id, "yaml")
        if design is not None:
            zf.writestr("design.yaml", design)
        trace_json = export_trace(run_id, "json")
        if trace_json is not None:
            zf.writestr("trace.json", trace_json)
        trace_jsonl = export_trace(run_id, "jsonl")
        if trace_jsonl is not None:
            zf.writestr("trace.jsonl", trace_jsonl)
        score = export_scorecard(run_id)
        if score is not None:
            zf.writestr("score.json", score)

        snapshots_path = run_dir / "build_snapshots.json"
        if snapshots_path.exists():
            zf.write(snapshots_path, "build_snapshots.json")
        else:
            zf.writestr("build_snapshots.json", "[]\n")

        toolcalls_path = run_dir / "toolcalls.jsonl"
        if toolcalls_path.exists():
            zf.write(toolcalls_path, "toolcalls.jsonl")
        interactions_path = run_dir / "model_interactions.json"
        if interactions_path.exists():
            zf.write(interactions_path, "model_interactions.json")
        for name in ("launch_config.json", "launch_provenance.json"):
            artifact = run_dir / name
            if artifact.exists():
                zf.write(artifact, name)

    return package.getvalue()
