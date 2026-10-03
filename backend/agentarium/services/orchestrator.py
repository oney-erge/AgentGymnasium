from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from agentarium.agents.runner import (
    _MAX_SIM_DURATION_SECONDS,
    AttemptResult,
    run_agent_attempt,
    run_cooperative_attempt,
)
from agentarium.core.schemas.design import WORLD_AUTHOR, DesignSpec
from agentarium.core.schemas.setup import (
    AgentConfig,
    CollaborationMode,
    LaunchConfig,
)
from agentarium.services.preset_service import get_scenario_preset
from agentarium.services.run_service import record_launch_config

# Delay between streamed tool_call events so the UI sees them arrive one at a
# time. Tests set this to 0.0 to keep runs fast.
STREAM_DELAY = 0.02

# Ceiling on attempts per run. The user's ``constraints.max_attempts`` is honored
# up to this ceiling (effective = min(requested, ceiling)), so designs can iterate
# toward a richer result while a runaway request stays bounded.
MAX_ATTEMPTS_CAP = 8

# Competitive: per-participant ceiling (runs are sequential — agent A fully, then
# agent B — so total work scales with participants).
COMPETITIVE_ATTEMPTS_CAP = 4

# Cooperative: every attempt runs ALL participants against ONE shared design
# before a single simulation/score, so each attempt is expensive.
COOPERATIVE_ATTEMPTS_CAP = 4

# Relay alternates participants while passing the previous scored-attempt
# summary forward. Sandbox gives each participant one independent trial.
RELAY_ATTEMPTS_CAP = 8
SANDBOX_PARTICIPANTS_CAP = 8

# Bound how many runs (with their buffered event history) we retain in memory.
# Only finished runs are evicted, oldest first, so an in-flight run is never
# dropped. Keeps a long-lived server from growing without limit.
MAX_RETAINED_RUNS = 100


def _design_summary(design: DesignSpec) -> dict:
    """Approximate part categories from a DesignSpec.

    The design schema does not track beam/ramp/sensor categories, so we
    approximate: motors are joints with ``motor_rate`` set; other categories are
    0 unless we can infer them. Seeded world/terrain/task parts (``created_by ==
    'world'``) are excluded so the panel shows what the AGENT built.
    """
    agent_bodies = [b for b in design.bodies if b.created_by != WORLD_AUTHOR]
    agent_joints = [j for j in design.joints if j.created_by != WORLD_AUTHOR]
    bodies = len(agent_bodies)
    joints = len(agent_joints)
    motors = sum(1 for j in agent_joints if j.motor_rate is not None)

    # Per-kind breakdown so the UI shows what was built (houses/towers/trees/…).
    by_kind: dict[str, int] = {}
    for b in agent_bodies:
        key = b.kind or b.shape.value
        by_kind[key] = by_kind.get(key, 0) + 1

    return {
        "bodies": bodies,
        "joints": joints,
        "motors": motors,
        "sensors": 0,
        # Derived from the kind labels rather than hardcoded zeros.
        "beams": by_kind.get("beam", 0),
        "ramps": by_kind.get("ramp", 0),
        "by_kind": by_kind,
        "total_parts": bodies + joints,
    }


def _ownership_by_agent(design: DesignSpec) -> dict[str, dict]:
    """Per-``created_by`` breakdown of who built which parts of a design.

    Used by cooperative mode so the UI can attribute parts of the SINGLE shared
    design to each contributing agent.
    """
    by_agent: dict[str, dict] = {}
    for body in design.bodies:
        agent_id = body.created_by or "unknown"
        bucket = by_agent.setdefault(
            agent_id, {"bodies": 0, "joints": 0, "motors": 0, "total_parts": 0}
        )
        bucket["bodies"] += 1
        bucket["total_parts"] += 1
    for joint in design.joints:
        agent_id = joint.created_by or "unknown"
        bucket = by_agent.setdefault(
            agent_id, {"bodies": 0, "joints": 0, "motors": 0, "total_parts": 0}
        )
        bucket["joints"] += 1
        bucket["total_parts"] += 1
        if joint.motor_rate is not None:
            bucket["motors"] += 1
    return by_agent


class _RunState:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue[dict]] = set()
        self.finished: bool = False
        # Strong reference to the background task. asyncio only keeps a weak
        # reference, so without this the run could be garbage-collected
        # mid-execution. Cleared in _run's finally.
        self.task: asyncio.Task[None] | None = None


class RunManager:
    """In-memory manager that runs launches as background tasks and broadcasts
    events to WebSocket subscribers while buffering full history for late
    subscribers."""

    def __init__(self) -> None:
        self._runs: dict[str, _RunState] = {}

    # ── Event plumbing ────────────────────────────────────────────────────

    def _emit(self, run_id: str, event: dict) -> None:
        state = self._runs.get(run_id)
        if state is None:
            return
        state.events.append(event)
        for queue in list(state.subscribers):
            queue.put_nowait(event)

    def get_events(self, run_id: str) -> list[dict]:
        state = self._runs.get(run_id)
        return list(state.events) if state is not None else []

    def is_finished(self, run_id: str) -> bool:
        state = self._runs.get(run_id)
        return state.finished if state is not None else False

    # ── Public API ────────────────────────────────────────────────────────

    async def create_run(
        self,
        config: LaunchConfig,
        provenance: dict | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex
        record_launch_config(
            run_id,
            config,
            {
                "kind": "launch",
                **(provenance or {}),
            },
        )
        state = _RunState()
        self._runs[run_id] = state
        self._evict_finished_runs()
        # Retain a strong reference so the task isn't GC'd mid-run.
        state.task = asyncio.create_task(self._run(run_id, config))
        return run_id

    def _evict_finished_runs(self) -> None:
        """Drop the oldest FINISHED runs once over the cap (never in-flight ones)."""
        while len(self._runs) > MAX_RETAINED_RUNS:
            oldest_finished = next(
                (rid for rid, st in self._runs.items() if st.finished), None
            )
            if oldest_finished is None:
                break  # all remaining runs are still in-flight
            self._runs.pop(oldest_finished, None)

    async def subscribe(self, run_id: str) -> AsyncIterator[dict]:
        state = self._runs.get(run_id)
        if state is None:
            yield {"type": "error", "detail": "unknown run"}
            return

        queue: asyncio.Queue[dict] = asyncio.Queue()
        # Replay buffered history first, then attach for live events. Snapshot
        # the buffer length before registering so we don't double-deliver.
        buffered = list(state.events)
        state.subscribers.add(queue)
        try:
            already_finished = state.finished
            for event in buffered:
                yield event
                if event.get("type") == "run_finished":
                    return
            if already_finished:
                # Run completed before we attached; buffered history is complete.
                return
            while True:
                event = await queue.get()
                yield event
                if event.get("type") == "run_finished":
                    return
        finally:
            state.subscribers.discard(queue)

    # ── Background execution ──────────────────────────────────────────────

    async def _run(self, run_id: str, config: LaunchConfig) -> None:
        try:
            await self._run_inner(run_id, config)
        except Exception as exc:  # noqa: BLE001 - surface failures to subscribers
            # Carry the structured kind (auth/timeout/server/…) when an LLM call
            # failed, so the UI can show an actionable reason.
            event = {"type": "error", "detail": str(exc)}
            kind = getattr(exc, "kind", None)
            if isinstance(kind, str):
                event["kind"] = kind
            self._emit(run_id, event)
            self._emit(
                run_id,
                {
                    "type": "run_finished",
                    "best_attempt_index": -1,
                    "best_score": 0.0,
                    "best_trace_run_id": None,
                },
            )
        finally:
            state = self._runs.get(run_id)
            if state is not None:
                state.finished = True

    async def _run_inner(self, run_id: str, config: LaunchConfig) -> None:
        objective = config.scenario.objective or config.scenario.preset
        preset = get_scenario_preset(config.scenario.preset)
        project_name = config.project_name
        if preset is not None and project_name in (
            "",
            "AgentGymnasium Run",
            "Agentarium Run",  # the project's former default name, possibly saved in old configs
            "Bridge Builder Lab",
        ):
            project_name = preset.name

        participants = list(config.agents.participants)
        if not participants:
            raise ValueError("config.agents.participants is empty")

        # Report the cap actually used for this mode so the UI's attempt count
        # matches reality (competitive/cooperative use smaller caps than single).
        mode_cap = {
            CollaborationMode.competitive: COMPETITIVE_ATTEMPTS_CAP,
            CollaborationMode.cooperative: COOPERATIVE_ATTEMPTS_CAP,
            CollaborationMode.relay: RELAY_ATTEMPTS_CAP,
            CollaborationMode.sandbox: min(
                len(participants), SANDBOX_PARTICIPANTS_CAP
            ),
        }.get(config.agents.mode, MAX_ATTEMPTS_CAP)

        self._emit(
            run_id,
            {
                "type": "run_started",
                "run_id": run_id,
                "project_name": project_name,
                "mode": config.agents.mode.value,
                "objective": objective,
                "reward": config.scenario.reward,
                "max_attempts": min(config.constraints.max_attempts, mode_cap),
                # Surface the effective MVP caps vs. what the user requested so the
                # UI can say "running 3 of 50" and "sim capped at 30s".
                "requested_attempts": config.constraints.max_attempts,
                "attempts_cap": mode_cap,
                "requested_duration_s": config.constraints.simulation_duration_seconds,
                "simulation_cap_s": _MAX_SIM_DURATION_SECONDS,
                "constraints": {
                    "max_parts": config.constraints.max_parts,
                    "max_joints": config.constraints.max_joints,
                    "max_motors": config.constraints.max_motors,
                    "energy_budget": config.constraints.energy_budget,
                    "simulation_duration_seconds": (
                        config.constraints.simulation_duration_seconds
                    ),
                },
                "agents": [
                    {"id": a.id, "name": a.name, "role": a.role.value}
                    for a in participants
                ],
            },
        )

        if config.agents.mode == CollaborationMode.competitive:
            await self._run_competitive(run_id, config, participants)
        elif config.agents.mode == CollaborationMode.cooperative:
            await self._run_cooperative(run_id, config, participants)
        elif config.agents.mode == CollaborationMode.relay:
            await self._run_relay(run_id, config, participants)
        elif config.agents.mode == CollaborationMode.sandbox:
            await self._run_sandbox(run_id, config, participants)
        else:
            await self._run_single_agent(run_id, config, participants[0])

    async def _run_agent_attempts(
        self,
        run_id: str,
        config: LaunchConfig,
        agent: AgentConfig,
        attempts: int,
        *,
        previous: AttemptResult | None = None,
        attempt_offset: int = 0,
        force_memory: bool = False,
    ) -> tuple[int, float, str | None, AttemptResult | None]:
        """Run ``attempts`` attempts for ``agent``, emitting per-agent events.

        Each attempt is given the previous attempt as its parent so the runner
        can record lineage and (with episodic memory) iterate on it.

        Returns the best summary plus the last result for relay handoffs.
        """
        best_attempt_index = -1
        best_score = float("-inf")
        best_trace_run_id: str | None = None
        for local_index in range(attempts):
            attempt_index = attempt_offset + local_index
            self._emit(
                run_id,
                {
                    "type": "attempt_started",
                    "attempt_index": attempt_index,
                    "agent_id": agent.id,
                    "parent_attempt_id": (
                        previous.attempt_id if previous is not None else None
                    ),
                },
            )

            result = await run_agent_attempt(
                config,
                agent,
                attempt_index=attempt_index,
                previous=previous,
                parent_run_id=run_id,
                force_memory=force_memory,
            )
            previous = result

            for interaction in result.model_interactions:
                model_result = interaction.result
                self._emit(
                    run_id,
                    {
                        "type": "model_result",
                        "attempt_index": attempt_index,
                        "agent_id": interaction.agent_id,
                        "turn_index": interaction.turn_index,
                        "provider": model_result.provider,
                        "model": model_result.model,
                        "latency_ms": model_result.latency_ms,
                        "retries": model_result.retries,
                        "finish_reason": model_result.finish_reason,
                        "native_tool_calls": model_result.native_tool_calls,
                        "usage": model_result.usage.model_dump(mode="json"),
                    },
                )

            for step_index, record in enumerate(result.tool_calls):
                self._emit(
                    run_id,
                    {
                        "type": "tool_call",
                        "attempt_index": attempt_index,
                        "agent_id": agent.id,
                        "record": record.model_dump(mode="json"),
                    },
                )
                # One durable build step per tool call, in lockstep, so the
                # Studio can scrub construction and label no-op/rejected steps.
                if step_index < len(result.build_steps):
                    step = result.build_steps[step_index]
                    self._emit(
                        run_id,
                        {
                            "type": "design_snapshot",
                            "attempt_index": attempt_index,
                            "agent_id": agent.id,
                            "step_index": step.step_index,
                            "trace_run_id": step.trace_run_id,
                            "tool": step.tool,
                            "status": step.status.value,
                            "label": step.label,
                            "mutated": step.mutated,
                            "visual_change": step.visual_change,
                            "new_body_ids": step.new_body_ids,
                            "new_joint_ids": step.new_joint_ids,
                            "error": step.error,
                            "trace": step.trace,
                        },
                    )
                if STREAM_DELAY:
                    await asyncio.sleep(STREAM_DELAY)

            self._emit(
                run_id,
                {
                    "type": "design_update",
                    "attempt_index": attempt_index,
                    "agent_id": agent.id,
                    "summary": _design_summary(result.design),
                },
            )

            if result.trace_run_id:
                self._emit(
                    run_id,
                    {
                        "type": "trace_ready",
                        "attempt_index": attempt_index,
                        "agent_id": agent.id,
                        "trace_run_id": result.trace_run_id,
                    },
                )

            self._emit(
                run_id,
                {
                    "type": "score",
                    "attempt_index": attempt_index,
                    "agent_id": agent.id,
                    "scorecard": result.score.model_dump(mode="json"),
                    "diff": result.diff,
                },
            )

            if result.score.score_total > best_score:
                best_score = result.score.score_total
                best_attempt_index = attempt_index
                best_trace_run_id = result.trace_run_id

            self._emit(
                run_id,
                {
                    "type": "attempt_finished",
                    "attempt_index": attempt_index,
                    "agent_id": agent.id,
                },
            )

        return best_attempt_index, best_score, best_trace_run_id, previous

    async def _run_single_agent(
        self, run_id: str, config: LaunchConfig, agent: AgentConfig
    ) -> None:
        attempts = min(config.constraints.max_attempts, MAX_ATTEMPTS_CAP)
        best_attempt_index, best_score, best_trace_run_id, _ = (
            await self._run_agent_attempts(run_id, config, agent, attempts)
        )
        self._emit(
            run_id,
            {
                "type": "run_finished",
                "best_attempt_index": best_attempt_index,
                "best_score": best_score if best_score != float("-inf") else 0.0,
                "best_trace_run_id": best_trace_run_id,
            },
        )

    async def _run_competitive(
        self,
        run_id: str,
        config: LaunchConfig,
        participants: list[AgentConfig],
    ) -> None:
        """Run each participant sequentially (agent A fully, then agent B, …).

        Interleaving is sequential for MVP — simpler and deterministic. Each
        agent gets a small attempt cap for responsiveness.
        """
        attempts = min(config.constraints.max_attempts, COMPETITIVE_ATTEMPTS_CAP)

        # agent_id -> best score across that agent's attempts.
        best_by_agent: dict[str, float] = {}
        best_attempt_by_agent: dict[str, int] = {}
        best_trace_by_agent: dict[str, str | None] = {}

        for agent in participants:
            best_index, best_score, best_trace, _ = await self._run_agent_attempts(
                run_id, config, agent, attempts
            )
            best_by_agent[agent.id] = (
                best_score if best_score != float("-inf") else 0.0
            )
            best_attempt_by_agent[agent.id] = best_index
            best_trace_by_agent[agent.id] = best_trace

        # Winner: highest best score; tie → first participant (stable order).
        winner_agent_id = participants[0].id
        winner_score = best_by_agent[winner_agent_id]
        for agent in participants[1:]:
            if best_by_agent[agent.id] > winner_score:
                winner_agent_id = agent.id
                winner_score = best_by_agent[agent.id]

        self._emit(
            run_id,
            {
                "type": "winner",
                "agent_id": winner_agent_id,
                "score": winner_score,
            },
        )
        self._emit(
            run_id,
            {
                "type": "run_finished",
                "best_attempt_index": best_attempt_by_agent[winner_agent_id],
                "best_score": winner_score,
                "best_trace_run_id": best_trace_by_agent[winner_agent_id],
                "winner_agent_id": winner_agent_id,
            },
        )

    async def _run_cooperative(
        self,
        run_id: str,
        config: LaunchConfig,
        participants: list[AgentConfig],
    ) -> None:
        """Run cooperative attempts: all participants build ONE shared design.

        Each attempt runs every participant in order against a single shared
        DesignSpec, then simulates and scores that shared design ONCE. There is
        no winner — the score is shared. Capped small for MVP responsiveness.
        """
        attempts = min(config.constraints.max_attempts, COOPERATIVE_ATTEMPTS_CAP)
        agent_ids = [a.id for a in participants]

        best_attempt_index = -1
        best_score = float("-inf")
        best_trace_run_id: str | None = None

        for attempt_index in range(attempts):
            # One shared attempt: announce it with the participating agent ids
            # rather than a single owner.
            self._emit(
                run_id,
                {
                    "type": "attempt_started",
                    "attempt_index": attempt_index,
                    "agent_ids": agent_ids,
                },
            )

            result = await run_cooperative_attempt(
                config,
                attempt_index=attempt_index,
                parent_run_id=run_id,
            )

            for interaction in result.model_interactions:
                model_result = interaction.result
                self._emit(
                    run_id,
                    {
                        "type": "model_result",
                        "attempt_index": attempt_index,
                        "agent_id": interaction.agent_id,
                        "turn_index": interaction.turn_index,
                        "provider": model_result.provider,
                        "model": model_result.model,
                        "latency_ms": model_result.latency_ms,
                        "retries": model_result.retries,
                        "finish_reason": model_result.finish_reason,
                        "native_tool_calls": model_result.native_tool_calls,
                        "usage": model_result.usage.model_dump(mode="json"),
                    },
                )

            # Stream each tool call attributed to its own author.
            for step_index, record in enumerate(result.tool_calls):
                self._emit(
                    run_id,
                    {
                        "type": "tool_call",
                        "attempt_index": attempt_index,
                        "agent_id": record.agent_id,
                        "record": record.model_dump(mode="json"),
                    },
                )
                if step_index < len(result.build_steps):
                    step = result.build_steps[step_index]
                    self._emit(
                        run_id,
                        {
                            "type": "design_snapshot",
                            "attempt_index": attempt_index,
                            "agent_id": record.agent_id,
                            "step_index": step.step_index,
                            "trace_run_id": step.trace_run_id,
                            "tool": step.tool,
                            "status": step.status.value,
                            "label": step.label,
                            "mutated": step.mutated,
                            "visual_change": step.visual_change,
                            "new_body_ids": step.new_body_ids,
                            "new_joint_ids": step.new_joint_ids,
                            "error": step.error,
                            "trace": step.trace,
                        },
                    )
                if STREAM_DELAY:
                    await asyncio.sleep(STREAM_DELAY)

            # One design_update for the shared design, with an ownership
            # breakdown so the UI can show who built what.
            self._emit(
                run_id,
                {
                    "type": "design_update",
                    "attempt_index": attempt_index,
                    "agent_ids": agent_ids,
                    "summary": _design_summary(result.design),
                    "by_agent": _ownership_by_agent(result.design),
                },
            )

            if result.trace_run_id:
                self._emit(
                    run_id,
                    {
                        "type": "trace_ready",
                        "attempt_index": attempt_index,
                        "agent_ids": agent_ids,
                        "trace_run_id": result.trace_run_id,
                    },
                )

            # A SINGLE shared score (not one per agent). diff is None for
            # cooperative (no per-attempt lineage) but emitted for shape parity.
            self._emit(
                run_id,
                {
                    "type": "score",
                    "attempt_index": attempt_index,
                    "agent_id": "shared",
                    "scorecard": result.score.model_dump(mode="json"),
                    "diff": result.diff,
                },
            )

            if result.score.score_total > best_score:
                best_score = result.score.score_total
                best_attempt_index = attempt_index
                best_trace_run_id = result.trace_run_id

            self._emit(
                run_id,
                {
                    "type": "attempt_finished",
                    "attempt_index": attempt_index,
                    "agent_ids": agent_ids,
                },
            )

        # No winner in cooperative mode — the score is shared.
        self._emit(
            run_id,
            {
                "type": "run_finished",
                "best_attempt_index": best_attempt_index,
                "best_score": best_score if best_score != float("-inf") else 0.0,
                "best_trace_run_id": best_trace_run_id,
                "winner_agent_id": None,
            },
        )

    async def _run_relay(
        self,
        run_id: str,
        config: LaunchConfig,
        participants: list[AgentConfig],
    ) -> None:
        """Alternate agents and pass scored-attempt memory down one lineage."""
        attempts = min(config.constraints.max_attempts, RELAY_ATTEMPTS_CAP)
        previous: AttemptResult | None = None
        best_attempt_index = -1
        best_score = float("-inf")
        best_trace_run_id: str | None = None

        for attempt_index in range(attempts):
            agent = participants[attempt_index % len(participants)]
            index, score, trace_id, previous = await self._run_agent_attempts(
                run_id,
                config,
                agent,
                1,
                previous=previous,
                attempt_offset=attempt_index,
                force_memory=True,
            )
            if score > best_score:
                best_attempt_index = index
                best_score = score
                best_trace_run_id = trace_id

        self._emit(
            run_id,
            {
                "type": "run_finished",
                "best_attempt_index": best_attempt_index,
                "best_score": best_score if best_score != float("-inf") else 0.0,
                "best_trace_run_id": best_trace_run_id,
                "winner_agent_id": None,
            },
        )

    async def _run_sandbox(
        self,
        run_id: str,
        config: LaunchConfig,
        participants: list[AgentConfig],
    ) -> None:
        """Give every participant one independent trial without declaring a winner."""
        best_attempt_index = -1
        best_score = float("-inf")
        best_trace_run_id: str | None = None

        for attempt_index, agent in enumerate(
            participants[:SANDBOX_PARTICIPANTS_CAP]
        ):
            index, score, trace_id, _ = await self._run_agent_attempts(
                run_id,
                config,
                agent,
                1,
                attempt_offset=attempt_index,
            )
            if score > best_score:
                best_attempt_index = index
                best_score = score
                best_trace_run_id = trace_id

        self._emit(
            run_id,
            {
                "type": "run_finished",
                "best_attempt_index": best_attempt_index,
                "best_score": best_score if best_score != float("-inf") else 0.0,
                "best_trace_run_id": best_trace_run_id,
                "winner_agent_id": None,
            },
        )


run_manager = RunManager()
