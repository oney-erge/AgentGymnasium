from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
import threading
import uuid

from agentgymnasium.core.schemas.design import BodyShape as _BodyShape
from agentgymnasium.core.schemas.design import (
    BodySpec,
    DesignSpec,
    JointSpec,
    JointType,
)
from agentgymnasium.core.schemas.model import ModelInteraction
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.setup import LaunchConfig, WorldConfig
from agentgymnasium.core.schemas.toolcall import BuildStepRecord
from agentgymnasium.core.schemas.trace import EpisodeTrace
from agentgymnasium.engines import get_engine
from agentgymnasium.services.scoring_service import score_attempt

logger = logging.getLogger(__name__)

# In-memory store of run traces.
RUNS: dict[str, EpisodeTrace] = {}

# In-memory store of scorecards, keyed by run_id (same key as RUNS).
SCORES: dict[str, ScoreCard] = {}

# In-memory store of the simulated design, keyed by run_id (same key as RUNS).
# Retained so exports can serialize the exact design behind a trace.
DESIGNS: dict[str, DesignSpec] = {}

# Bound in-memory retention so a long-lived server doesn't grow without limit.
# The three stores share the same keys and are evicted together (oldest first);
# on-disk artifacts under runs/{run_id}/ are not touched. 200 keeps plenty of
# recent attempts replayable while capping memory.
_MAX_RETAINED_RUNS = 200

# Run artifacts directory (gitignored), relative to cwd.
_RUNS_DIR = pathlib.Path("runs")

# SQLite persistence — survives server restarts.
# A database created under the project's former name (agentarium.db) keeps being used until the
# new file exists, so run history is not lost by the rename.
def _default_db_path(runs_dir: pathlib.Path) -> pathlib.Path:
    legacy = runs_dir / "agentarium.db"
    current = runs_dir / "agentgymnasium.db"
    return legacy if legacy.exists() and not current.exists() else current


_DB_PATH = _default_db_path(_RUNS_DIR)
_DB_MAX_ROWS = 1000  # keep at most 1000 runs on disk
_db_lock = threading.Lock()


def _init_db() -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                trace_json TEXT NOT NULL,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
            CREATE TABLE IF NOT EXISTS scores (
                run_id TEXT PRIMARY KEY,
                score_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS designs (
                run_id TEXT PRIMARY KEY,
                design_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_configs (
                run_id TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
            -- Queryable summary for run history + leaderboards (resume after restart).
            CREATE TABLE IF NOT EXISTS run_meta (
                run_id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                project_name TEXT,
                challenge TEXT,
                mode TEXT,
                reward TEXT,
                score_total REAL,
                success INTEGER,
                artifact_dir TEXT,
                -- Parent live-launch id shared by every attempt of one launch, so
                -- run history can collapse a launch's attempts into a single row.
                parent_run_id TEXT,
                provider TEXT,
                model TEXT,
                seed INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                latency_ms REAL,
                protocol TEXT,
                benchmark_hash TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_meta_challenge_score
                ON run_meta (challenge, score_total DESC);
        """)
        # Migrate pre-existing DBs that predate the parent_run_id column.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(run_meta)")}
        if "parent_run_id" not in cols:
            conn.execute("ALTER TABLE run_meta ADD COLUMN parent_run_id TEXT")
        migrations = {
            "provider": "TEXT",
            "model": "TEXT",
            "seed": "INTEGER",
            "input_tokens": "INTEGER",
            "output_tokens": "INTEGER",
            "latency_ms": "REAL",
            "protocol": "TEXT",
            "benchmark_hash": "TEXT",
        }
        for column, column_type in migrations.items():
            if column not in cols:
                conn.execute(f"ALTER TABLE run_meta ADD COLUMN {column} {column_type}")


# Only these columns may be written via _db_upsert_meta — guards the f-string
# column interpolation against ever taking an attacker-controlled key.
_META_COLUMNS = frozenset(
    {
        "project_name",
        "challenge",
        "mode",
        "reward",
        "score_total",
        "success",
        "artifact_dir",
        "parent_run_id",
        "provider",
        "model",
        "seed",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "protocol",
        "benchmark_hash",
    }
)


def _db_upsert_meta(run_id: str, **fields: object) -> None:
    """Insert or update the run_meta row for ``run_id`` with the given fields."""
    if not fields:
        return
    bad = set(fields) - _META_COLUMNS
    if bad:
        raise ValueError(f"unknown run_meta columns: {sorted(bad)}")
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{c}=excluded.{c}" for c in fields)
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                f"INSERT INTO run_meta (run_id, {cols}) VALUES (?, {placeholders}) "
                f"ON CONFLICT(run_id) DO UPDATE SET {updates}",
                (run_id, *fields.values()),
            )
            conn.commit()


def _db_write_run(run_id: str, trace: EpisodeTrace, design: DesignSpec) -> None:
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, trace_json) VALUES (?, ?)",
                (run_id, trace.model_dump_json()),
            )
            conn.execute(
                "INSERT OR REPLACE INTO designs (run_id, design_json) VALUES (?, ?)",
                (run_id, design.model_dump_json()),
            )
            # Prune oldest rows beyond the on-disk cap, then drop scores/designs
            # whose run was pruned so those tables don't grow without bound.
            conn.execute(
                "DELETE FROM runs WHERE run_id NOT IN "
                "(SELECT run_id FROM runs ORDER BY rowid DESC LIMIT ?)",
                (_DB_MAX_ROWS,),
            )
            conn.execute("DELETE FROM scores WHERE run_id NOT IN (SELECT run_id FROM runs)")
            conn.execute("DELETE FROM designs WHERE run_id NOT IN (SELECT run_id FROM runs)")
            # Keep run_meta in lockstep with runs so history/leaderboard never
            # link to a run whose trace was evicted (no dead links, bounded growth).
            conn.execute("DELETE FROM run_meta WHERE run_id NOT IN (SELECT run_id FROM runs)")
            conn.commit()


def _db_write_score(run_id: str, score: ScoreCard) -> None:
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scores (run_id, score_json) VALUES (?, ?)",
                (run_id, score.model_dump_json()),
            )
            conn.commit()


def record_launch_config(
    run_id: str,
    config: LaunchConfig,
    provenance: dict | None = None,
) -> None:
    """Persist the exact LaunchConfig that produced or owns ``run_id``.

    ``run_id`` may be either the parent live launch id returned by
    ``/api/setup/launch`` or an individual simulated attempt trace id. Storing
    both makes Studio and History equally reproducible.
    """
    provenance = provenance or {}
    # Run artifacts are routinely exported and shared. Credentials are runtime
    # inputs, never reproducibility metadata, so persist only a redacted copy.
    persisted_config = config.model_copy(deep=True)
    persisted_config.llm_connection.api_key = None
    for participant in persisted_config.agents.participants:
        participant.api_key = None
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO run_configs "
                "(run_id, config_json, provenance_json) VALUES (?, ?, ?)",
                (
                    run_id,
                    persisted_config.model_dump_json(),
                    json.dumps(provenance, sort_keys=True),
                ),
            )
            conn.commit()

    # Mirror the config into the artifact dir so a copied run folder is
    # self-contained even without the SQLite database.
    run_dir = _RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "launch_config.json").write_text(
        persisted_config.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_dir / "launch_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8"
    )


def get_launch_config(run_id: str) -> LaunchConfig | None:
    """Return the persisted LaunchConfig for ``run_id`` if one was captured."""
    if _DB_PATH.exists():
        with _db_lock:
            with sqlite3.connect(_DB_PATH) as conn:
                row = conn.execute(
                    "SELECT config_json FROM run_configs WHERE run_id = ?", (run_id,)
                ).fetchone()
        if row is not None:
            try:
                return LaunchConfig.model_validate_json(row[0])
            except Exception:
                return None

    path = _RUNS_DIR / run_id / "launch_config.json"
    if not path.is_file():
        return None
    try:
        return LaunchConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_launch_provenance(run_id: str) -> dict:
    """Return best-effort provenance metadata for a captured launch config."""
    if _DB_PATH.exists():
        with _db_lock:
            with sqlite3.connect(_DB_PATH) as conn:
                row = conn.execute(
                    "SELECT provenance_json FROM run_configs WHERE run_id = ?", (run_id,)
                ).fetchone()
        if row is not None:
            try:
                value = json.loads(row[0])
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}

    path = _RUNS_DIR / run_id / "launch_provenance.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _db_get_trace(run_id: str) -> EpisodeTrace | None:
    if not _DB_PATH.exists():
        return None
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            row = conn.execute(
                "SELECT trace_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
    if row is None:
        return None
    try:
        return EpisodeTrace.model_validate_json(row[0])
    except Exception:
        return None


def _db_get_score(run_id: str) -> ScoreCard | None:
    if not _DB_PATH.exists():
        return None
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            row = conn.execute(
                "SELECT score_json FROM scores WHERE run_id = ?", (run_id,)
            ).fetchone()
    if row is None:
        return None
    try:
        return ScoreCard.model_validate_json(row[0])
    except Exception:
        return None


def _db_get_design(run_id: str) -> DesignSpec | None:
    if not _DB_PATH.exists():
        return None
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            row = conn.execute(
                "SELECT design_json FROM designs WHERE run_id = ?", (run_id,)
            ).fetchone()
    if row is None:
        return None
    try:
        return DesignSpec.model_validate_json(row[0])
    except Exception:
        return None


def _load_from_db() -> None:
    """Populate in-memory stores from DB on startup (most recent _MAX_RETAINED_RUNS)."""
    if not _DB_PATH.exists():
        return
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT run_id, trace_json FROM runs ORDER BY rowid DESC LIMIT ?",
                (_MAX_RETAINED_RUNS,),
            ).fetchall()
            run_ids = []
            for run_id, trace_json in reversed(rows):
                try:
                    RUNS[run_id] = EpisodeTrace.model_validate_json(trace_json)
                    run_ids.append(run_id)
                except Exception:
                    pass
            for run_id in run_ids:
                row = conn.execute(
                    "SELECT score_json FROM scores WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row:
                    try:
                        SCORES[run_id] = ScoreCard.model_validate_json(row[0])
                    except Exception:
                        pass
                row = conn.execute(
                    "SELECT design_json FROM designs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row:
                    try:
                        DESIGNS[run_id] = DesignSpec.model_validate_json(row[0])
                    except Exception:
                        pass
    except Exception:
        pass  # startup DB load is best-effort; server continues with empty stores


# Initialise DB and load existing runs on module import (best-effort).
try:
    _init_db()
    _load_from_db()
except Exception:
    pass


def _evict_oldest_runs() -> None:
    """Drop the oldest run(s) from all in-memory stores once over the cap.

    Dicts preserve insertion order, so the first key is the oldest run.
    """
    while len(RUNS) > _MAX_RETAINED_RUNS:
        oldest = next(iter(RUNS))
        RUNS.pop(oldest, None)
        SCORES.pop(oldest, None)
        DESIGNS.pop(oldest, None)


def hardcoded_demo_design() -> DesignSpec:
    """A small valid design that visibly moves under gravity.

    A falling box and a ball, plus a two-body pivot joint.
    """
    return DesignSpec(
        name="demo",
        bodies=[
            BodySpec(
                id="box",
                shape=_BodyShape.box,
                position=[0.0, 8.0],
                size=[1.0, 1.0],
                mass=1.0,
                color="#cc5544",
            ),
            BodySpec(
                id="ball",
                shape=_BodyShape.circle,
                position=[3.0, 10.0],
                size=[0.5],
                mass=1.0,
                color="#4488cc",
            ),
            BodySpec(
                id="arm_a",
                shape=_BodyShape.box,
                position=[-4.0, 6.0],
                size=[1.5, 0.3],
                mass=1.0,
            ),
            BodySpec(
                id="arm_b",
                shape=_BodyShape.box,
                position=[-2.5, 6.0],
                size=[1.5, 0.3],
                mass=1.0,
            ),
        ],
        joints=[
            JointSpec(
                id="pivot1",
                body_a="arm_a",
                body_b="arm_b",
                type=JointType.pivot,
                anchor_a=[0.75, 0.0],
            ),
        ],
    )


def create_run_from_design(
    design: DesignSpec,
    world: WorldConfig,
    duration_seconds: float = 5.0,
    launch_config: LaunchConfig | None = None,
    provenance: dict | None = None,
    parent_run_id: str | None = None,
) -> str:
    """Run ``design`` with the engine named by ``world.engine`` and store the trace.

    Returns the generated run_id.
    """
    engine = get_engine(world.engine.value)
    if engine is None:
        raise ValueError(f"Unsupported engine: {world.engine.value}")

    run_id = uuid.uuid4().hex
    if launch_config is not None:
        try:
            record_launch_config(run_id, launch_config, provenance)
        except Exception:  # noqa: BLE001 - config capture must not suppress a trace
            logger.warning("Failed to capture launch config for run %s", run_id, exc_info=True)

    trace = engine.simulate(design, world, duration_seconds)
    trace.run_id = run_id

    RUNS[run_id] = trace
    DESIGNS[run_id] = design

    # Compute and store a baseline ScoreCard so every run has a fetchable
    # score. The runner may overwrite this with a reward-specific score.
    baseline = score_attempt(trace, design, "default")
    SCORES[run_id] = baseline
    _evict_oldest_runs()

    # Persist trace + design to SQLite and trace.json to the artifact dir.
    _db_write_run(run_id, trace, design)
    _db_write_score(run_id, baseline)

    run_dir = _RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trace.json").write_text(
        trace.model_dump_json(indent=2), encoding="utf-8"
    )

    # Seed the run-history row with what we know here (challenge/mode/project are
    # filled in later by the runner via record_run_meta). ``parent_run_id`` links
    # this attempt to its launch so history can collapse a launch to one row.
    meta_fields: dict[str, object] = dict(
        score_total=baseline.score_total,
        success=int(baseline.success),
        reward=baseline.reward,
        artifact_dir=str(run_dir),
    )
    if parent_run_id is not None:
        meta_fields["parent_run_id"] = parent_run_id
    _db_upsert_meta(run_id, **meta_fields)

    return run_id


def record_run_meta(
    run_id: str,
    *,
    project_name: str | None = None,
    challenge: str | None = None,
    mode: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    seed: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: float | None = None,
    protocol: str | None = None,
    benchmark_hash: str | None = None,
) -> None:
    """Fill in run-history fields the runner knows (challenge/mode/project)."""
    fields = {
        k: v
        for k, v in (
            ("project_name", project_name),
            ("challenge", challenge),
            ("mode", mode),
            ("provider", provider),
            ("model", model),
            ("seed", seed),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("latency_ms", latency_ms),
            ("protocol", protocol),
            ("benchmark_hash", benchmark_hash),
        )
        if v is not None
    }
    if fields:
        _db_upsert_meta(run_id, **fields)


# One representative row per launch: the best-scoring attempt stands in for the
# whole launch, carrying an ``attempt_count`` of how many attempts it had. A
# standalone run (no parent_run_id) is its own group of one. Attempts of one
# launch therefore collapse to a single history/leaderboard row instead of N.
_RUN_GROUPS_CTE = """
    SELECT
        run_meta.*,
        run_meta.rowid AS _rowid,
        COUNT(*) OVER (
            PARTITION BY COALESCE(parent_run_id, run_id)
        ) AS attempt_count,
        MAX(created_at) OVER (
            PARTITION BY COALESCE(parent_run_id, run_id)
        ) AS _grp_created,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(parent_run_id, run_id)
            ORDER BY score_total IS NULL, score_total DESC, run_meta.rowid DESC
        ) AS _rn,
        EXISTS(
            SELECT 1 FROM run_configs
            WHERE run_configs.run_id = run_meta.run_id
        ) AS config_available
    FROM run_meta
"""

_GROUP_INTERNAL_KEYS = ("_rn", "_rowid", "_grp_created")


def _clean_group_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in _GROUP_INTERNAL_KEYS:
        d.pop(key, None)
    return d


def list_runs(limit: int = 50) -> list[dict]:
    """Most-recent launches first, one row per launch (survives restart)."""
    if not _DB_PATH.exists():
        return []
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM ({_RUN_GROUPS_CTE}) WHERE _rn = 1 "
                "ORDER BY _grp_created DESC, _rowid DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
    return [_clean_group_row(r) for r in rows]


def leaderboard(challenge: str | None = None, limit: int = 10) -> list[dict]:
    """Top launches by best score, optionally filtered to one challenge."""
    if not _DB_PATH.exists():
        return []
    query = (
        f"SELECT * FROM ({_RUN_GROUPS_CTE}) "
        "WHERE _rn = 1 AND score_total IS NOT NULL"
    )
    params: list[object] = []
    if challenge:
        query += " AND challenge = ?"
        params.append(challenge)
    else:
        # Exclude demo / ad-hoc runs (no challenge) from the global leaderboard.
        query += " AND challenge IS NOT NULL"
    query += " ORDER BY score_total DESC LIMIT ?"
    params.append(max(1, min(limit, 100)))
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
    return [_clean_group_row(r) for r in rows]


def list_run_attempts(run_id: str) -> list[dict]:
    """Return every attempt trace that belongs to the same run as ``run_id``.

    Attempts are linked to their parent live-launch run through the provenance
    captured in ``run_configs`` (``kind='attempt'`` + ``parent_run_id``). ``run_id``
    may be either the parent launch id (returned by ``/setup/launch``) or one of
    its individual attempt trace ids — in both cases the full sibling set is
    returned, sorted by agent then attempt index, so Studio can browse and replay
    any attempt of a finished run.
    """
    if not _DB_PATH.exists():
        return []
    with _db_lock:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            config_rows = conn.execute(
                "SELECT run_id, provenance_json FROM run_configs"
            ).fetchall()

            provs: dict[str, dict] = {}
            for row in config_rows:
                try:
                    parsed = json.loads(row["provenance_json"])
                except Exception:
                    parsed = {}
                provs[row["run_id"]] = parsed if isinstance(parsed, dict) else {}

            # If run_id is itself an attempt, group by its parent; otherwise treat
            # run_id as the parent id directly.
            parent = run_id
            own = provs.get(run_id, {})
            if own.get("kind") == "attempt" and own.get("parent_run_id"):
                parent = own["parent_run_id"]

            attempts = [
                (tid, prov)
                for tid, prov in provs.items()
                if prov.get("kind") == "attempt" and prov.get("parent_run_id") == parent
            ]
            if not attempts:
                return []

            result: list[dict] = []
            for tid, prov in attempts:
                meta = conn.execute(
                    "SELECT score_total, success FROM run_meta WHERE run_id = ?", (tid,)
                ).fetchone()
                result.append(
                    {
                        "trace_run_id": tid,
                        "attempt_index": prov.get("attempt_index"),
                        "agent_id": prov.get("agent_id"),
                        "score_total": meta["score_total"] if meta else None,
                        "success": (
                            None
                            if meta is None or meta["success"] is None
                            else bool(meta["success"])
                        ),
                    }
                )

    result.sort(
        key=lambda a: (
            a["agent_id"] or "",
            a["attempt_index"] if a["attempt_index"] is not None else 0,
        )
    )
    return result


def get_trace(run_id: str) -> EpisodeTrace | None:
    """Return the stored trace for ``run_id``, checking DB if evicted from memory."""
    return RUNS.get(run_id) or _db_get_trace(run_id)


def store_score(run_id: str, score: ScoreCard) -> None:
    """Store ``score`` for ``run_id`` so it can be fetched later."""
    SCORES[run_id] = score
    _db_write_score(run_id, score)
    # Keep the run-history summary in sync with the reward-specific score.
    _db_upsert_meta(
        run_id,
        score_total=score.score_total,
        success=int(score.success),
        reward=score.reward,
    )


def get_score(run_id: str) -> ScoreCard | None:
    """Return the stored ScoreCard for ``run_id``, checking DB if evicted from memory."""
    return SCORES.get(run_id) or _db_get_score(run_id)


def get_design(run_id: str) -> DesignSpec | None:
    """Return the design that produced ``run_id``'s trace, checking DB if evicted from memory."""
    return DESIGNS.get(run_id) or _db_get_design(run_id)


def get_build_snapshots(run_id: str) -> list[BuildStepRecord] | None:
    """Return persisted Build Timeline steps for ``run_id``.

    ``None`` means the run itself is unknown. An empty list means this is a
    known, usually older, run whose artifacts predate ``build_snapshots.json``.
    """
    if get_trace(run_id) is None:
        return None
    path = _RUNS_DIR / run_id / "build_snapshots.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [BuildStepRecord.model_validate(item) for item in raw]
    except Exception:
        return []


def get_model_interactions(run_id: str) -> list[ModelInteraction] | None:
    """Credential-free prompt/result turns persisted beside an attempt trace."""
    if get_trace(run_id) is None:
        return None
    path = _RUNS_DIR / run_id / "model_interactions.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [ModelInteraction.model_validate(item) for item in raw]
    except Exception:
        return []
