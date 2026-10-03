from __future__ import annotations

import json
import re

from agentgymnasium.agents.base import (
    AgentProvider,
    ProviderStatus,
    StructuredOutputResult,
)


def _body(bid: str, shape: str, pos: list[float], kind: str, **extra: object) -> dict:
    return {
        "tool": "create_body",
        "args": {"id": bid, "shape": shape, "position": pos, "kind": kind, **extra},
    }


# Generic fallback for ad-hoc/custom scenarios. It uses only create_body +
# run_simulation, which are broadly enabled, and produces a visible movable body
# instead of the old invisible/default body-at-origin trap.
_SAMPLE_TOOL_CALLS = [
    _body("crate_1", "box", [0.0, 3.0], "crate", width=1.0, height=1.0),
    {"tool": "run_simulation", "args": {}},
]


_BRIDGE_TOOL_CALLS = [
    # A single continuous, gently downhill deck from the slope's end
    # (~-4.4, 2.05) to the goal cliff top (x=2.5, y=1.55) — verified against
    # the real physics (island_cliff_small's ground_spans gap) to actually
    # carry the crate to the goal. One clean deck reads as a bridge; extra
    # "support" beams would just be decorative clutter (add_beam bodies are
    # always static/rigid, so nothing here can physically collapse).
    {
        "tool": "add_beam",
        "args": {
            "id": "bridge_deck",
            "start": [-4.4, 2.05],
            "end": [2.5, 1.55],
            "width": 0.22,
            "kind": "beam",
            "color": "#8b5a2b",
        },
    },
    {"tool": "run_simulation", "args": {}},
]


_CRAWL_TOOL_CALLS = [
    # Legs spawn just below+forward/behind the torso (which sits at [-5, 1.5] —
    # see crawl_challenge.yaml's scaffold); hip joints anchor at the torso's
    # underside (not its center) and the leg's own end (not its middle) — a
    # center-to-center pivot snaps the whole leg to the torso with a violent
    # jolt instead of a hinge. Motor rate/force validated against the real
    # engine: this bounds/hops forward and crosses threshold_x=6 with 0 falls
    # (see test_runner.py::test_crawl_with_real_physics_crosses_threshold).
    _body("front_leg", "segment", [-4.35, 1.1], "leg", length=1.0, mass=0.35, friction=0.95),
    _body("rear_leg", "segment", [-5.65, 1.1], "leg", length=1.0, mass=0.35, friction=0.95),
    {
        "tool": "add_joint",
        "args": {
            "id": "front_hip", "body_a": "torso", "body_b": "front_leg", "type": "pivot",
            "anchor_a": [0.5, -0.3], "anchor_b": [-0.5, 0.0],
        },
    },
    {
        "tool": "add_joint",
        "args": {
            "id": "rear_hip", "body_a": "torso", "body_b": "rear_leg", "type": "pivot",
            "anchor_a": [-0.5, -0.3], "anchor_b": [-0.5, 0.0],
        },
    },
    {"tool": "add_motor", "args": {"id": "front_drive", "joint_id": "front_hip", "rate": -1.2, "max_force": 200.0}},
    {"tool": "add_motor", "args": {"id": "rear_drive", "joint_id": "rear_hip", "rate": 1.2, "max_force": 200.0}},
    {"tool": "run_simulation", "args": {}},
]


_SORTER_TOOL_CALLS = [
    {
        "tool": "add_bin",
        "args": {
            "id": "red_bin",
            "position": [-3.0, 1.8],
            "width": 1.8,
            "height": 4.0,
            "accepts": "red",
            "kind": "bin",
            "color": "red",
        },
    },
    {
        "tool": "add_bin",
        "args": {
            "id": "blue_bin",
            "position": [-1.0, 1.8],
            "width": 1.8,
            "height": 4.0,
            "accepts": "blue",
            "kind": "bin",
            "color": "blue",
        },
    },
    {
        "tool": "add_ramp",
        "args": {
            "id": "red_chute",
            "start": [-3.7, 3.2],
            "end": [-3.0, 2.3],
            "kind": "ramp",
            "color": "red",
        },
    },
    {
        "tool": "add_ramp",
        "args": {
            "id": "blue_chute",
            "start": [-0.3, 3.2],
            "end": [-1.0, 2.3],
            "kind": "ramp",
            "color": "blue",
        },
    },
    {"tool": "run_simulation", "args": {}},
]


# A small but varied city scene (roads, a park, trees, buildings of different
# heights/kinds) so the no-LLM demo actually looks like a city, not one box.
# Used only when the objective is recognizably a city challenge (see complete()).
_CITY_TOOL_CALLS = [
    {"tool": "create_body", "args": {
        "id": "road1", "shape": "box", "kind": "road",
        "position": [0.0, 0.15], "width": 20.0, "height": 0.3, "static": True,
        "color": "#4b5563",
    }},
    {"tool": "create_body", "args": {
        "id": "park1", "shape": "box", "kind": "park",
        "position": [-9.0, 0.1], "width": 3.0, "height": 0.2, "static": True,
        "color": "#4ade80",
    }},
    {"tool": "create_body", "args": {
        "id": "house1", "shape": "box", "kind": "house",
        "position": [-6.0, 1.5], "width": 2.0, "height": 3.0, "static": True,
        "color": "#d9a066",
    }},
    {"tool": "create_body", "args": {
        "id": "tower1", "shape": "box", "kind": "tower",
        "position": [-2.5, 4.0], "width": 2.5, "height": 8.0, "static": True,
        "color": "#a78bfa",
    }},
    {"tool": "create_body", "args": {
        "id": "shop1", "shape": "box", "kind": "shop",
        "position": [1.0, 2.0], "width": 2.0, "height": 4.0, "static": True,
        "color": "#38bdf8",
    }},
    {"tool": "create_body", "args": {
        "id": "house2", "shape": "box", "kind": "house",
        "position": [4.0, 1.5], "width": 2.0, "height": 3.0, "static": True,
        "color": "#f59e0b",
    }},
    {"tool": "create_body", "args": {
        "id": "tower2", "shape": "box", "kind": "tower",
        "position": [7.5, 3.0], "width": 2.0, "height": 6.0, "static": True,
        "color": "#818cf8",
    }},
    {"tool": "create_body", "args": {
        "id": "tree1", "shape": "box", "kind": "tree",
        "position": [-4.0, 0.9], "width": 1.0, "height": 1.8, "static": True,
        "color": "#22c55e",
    }},
    {"tool": "create_body", "args": {
        "id": "tree2", "shape": "box", "kind": "tree",
        "position": [9.5, 0.9], "width": 1.0, "height": 1.8, "static": True,
        "color": "#22c55e",
    }},
    {"tool": "create_body", "args": {
        "id": "shop2", "shape": "box", "kind": "shop",
        "position": [12.0, 2.5], "width": 2.0, "height": 5.0, "static": True,
    }},
    {"tool": "run_simulation", "args": {}},
]


# A grid layout for the isometric City Builder challenge (city_builder — its
# reward_options select between city_planning/boomtown/budget_city/
# balanced_city/green_capital, but they all share this one build) — unlike
# _CITY_TOOL_CALLS (a single row along x for the pymunk2d side-view city),
# this varies BOTH x and z so the no-LLM demo actually shows depth/zoning/road
# connectivity in the iso renderer.
_CITY_BUILDER_TOOL_CALLS = [
    {"tool": "create_body", "args": {
        "id": "main_st", "shape": "box", "kind": "road", "position": [0.0, 0.0], "z": 0.0,
        "width": 24.0, "height": 0.2, "depth": 3.0, "static": True, "color": "#4b5563",
    }},
    {"tool": "create_body", "args": {
        "id": "cross_st", "shape": "box", "position": [0.0, 0.0], "z": 0.0,
        "width": 3.0, "height": 0.2, "depth": 20.0, "static": True, "color": "#4b5563",
        "kind": "road",
    }},
    {"tool": "create_body", "args": {
        "id": "house1", "shape": "box", "kind": "house",
        "position": [-8.0, 1.5], "z": 5.0, "width": 2.0, "height": 3.0, "static": True,
        "color": "#d9a066",
    }},
    {"tool": "create_body", "args": {
        "id": "house2", "shape": "box", "kind": "house",
        "position": [-4.0, 1.5], "z": 5.0, "width": 2.0, "height": 3.0, "static": True,
        "color": "#f59e0b",
    }},
    {"tool": "create_body", "args": {
        "id": "apartment1", "shape": "box", "kind": "apartment",
        "position": [-8.0, 3.0], "z": -5.0, "width": 3.0, "height": 6.0, "static": True,
        "color": "#c084fc",
    }},
    {"tool": "create_body", "args": {
        "id": "shop1", "shape": "box", "kind": "shop",
        "position": [4.0, 2.0], "z": 5.0, "width": 2.2, "height": 4.0, "static": True,
        "color": "#38bdf8",
    }},
    {"tool": "create_body", "args": {
        "id": "shop2", "shape": "box", "kind": "shop",
        "position": [8.0, 2.0], "z": 5.0, "width": 2.2, "height": 4.0, "static": True,
        "color": "#0ea5e9",
    }},
    {"tool": "create_body", "args": {
        "id": "factory1", "shape": "box", "kind": "factory",
        "position": [8.0, 2.5], "z": -6.0, "width": 3.5, "height": 5.0, "static": True,
        "color": "#78716c",
    }},
    {"tool": "create_body", "args": {
        "id": "school1", "shape": "box", "kind": "school",
        "position": [-2.0, 2.0], "z": -5.0, "width": 3.0, "height": 4.0, "static": True,
        "color": "#f87171",
    }},
    {"tool": "create_body", "args": {
        "id": "park1", "shape": "box", "kind": "park",
        "position": [3.0, 0.1], "z": -1.5, "width": 4.0, "height": 0.2, "depth": 4.0,
        "static": True, "color": "#4ade80",
    }},
    {"tool": "create_body", "args": {
        "id": "tree1", "shape": "box", "kind": "tree",
        "position": [-1.0, 0.9], "z": 2.0, "width": 1.0, "height": 1.8, "static": True,
        "color": "#22c55e",
    }},
    {"tool": "create_body", "args": {
        "id": "tree2", "shape": "box", "kind": "tree",
        "position": [1.5, 0.9], "z": 8.0, "width": 1.0, "height": 1.8, "static": True,
        "color": "#22c55e",
    }},
    {"tool": "run_simulation", "args": {"duration_seconds": 30.0}},
]


def _objective_from_user_prompt(user: str) -> str:
    prompt = user.lower()
    marker = "achieve:"
    if marker not in prompt:
        return prompt
    objective = prompt.split(marker, 1)[1].strip()
    objective = objective.split("\n", 1)[0]
    objective = objective.replace("emit your tool_calls now.", "")
    return objective.strip().removesuffix(".").strip()


def _calls_for_prompt(system: str, user: str) -> list[dict]:
    # Route from the per-attempt user prompt. The system prompt contains generic
    # examples/tool guidance, so scanning it first can accidentally trigger the
    # wrong challenge behavior (e.g. bridge examples on a distance challenge).
    # Cooperative prompts also list existing body ids, so narrow this to the
    # objective phrase and ignore "agent_a_crate_1"-style context.
    prompt = _objective_from_user_prompt(user)
    # Check the isometric citysim challenge (city_builder) BEFORE the generic
    # "city" keyword match below — its objective (and its bare preset id, "city
    # builder") also contains "city", so this must come first or it would
    # wrongly route to the old pymunk2d side-view city build. The reward-name
    # keywords (boomtown/budget_city/…) also match since a bare-objective test
    # config falls back to config.scenario.reward-adjacent wording in practice.
    if (
        "zoning" in prompt
        or "connectivity" in prompt
        or "road-connected" in prompt
        or "city_builder" in prompt
        or "city builder" in prompt
        or "boomtown" in prompt
        or "budget_city" in prompt
        or "balanced_city" in prompt
        or "green_capital" in prompt
    ):
        return _CITY_BUILDER_TOOL_CALLS
    if "city" in prompt or "plaza" in prompt or "park" in prompt:
        return _CITY_TOOL_CALLS
    if "sorter" in prompt or "sort " in prompt or "matching bin" in prompt:
        return _SORTER_TOOL_CALLS
    if "crawl" in prompt or "creature" in prompt or "threshold" in prompt:
        return _CRAWL_TOOL_CALLS
    if "bridge" in prompt or "crate" in prompt or "goal platform" in prompt:
        return _BRIDGE_TOOL_CALLS
    if "shared design" in user.lower():
        return [
            _body("crate_1", "box", [2.0, 3.0], "crate", width=1.0, height=1.0),
            {"tool": "run_simulation", "args": {}},
        ]
    return _SAMPLE_TOOL_CALLS


class MockProvider(AgentProvider):
    name = "mock"

    async def test_connection(
        self, endpoint_url: str | None, api_key: str | None
    ) -> ProviderStatus:
        return ProviderStatus(
            online=True,
            detail="Mock provider always available",
            models=["mock"],
        )

    async def test_structured_output(
        self, model: str, endpoint_url: str | None, api_key: str | None
    ) -> StructuredOutputResult:
        return StructuredOutputResult(
            ok=True,
            detail="Mock provider emits deterministic tool calls",
            sample=[dict(call) for call in _SAMPLE_TOOL_CALLS],
        )

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        endpoint_url: str | None,
        api_key: str | None,
        temperature: float = 0.7,
    ) -> str:
        # The objective/world context are embedded in the prompts. Emit a
        # challenge-specific deterministic build so the no-network demo is honest:
        # bridge -> beams, crawl -> legs/joints/motors, sorter -> bins/ramps,
        # city -> semantic city props. Custom prompts fall back to one crate.
        if "embodiment control tools" in system.lower():
            match = re.search(
                r"Goal: x=([-+0-9.eE]+), y=([-+0-9.eE]+)",
                system,
            )
            target_x = float(match.group(1)) if match else 0.0
            target_y = float(match.group(2)) if match else 0.0
            calls = [
                {
                    "tool": "drive_to",
                    "args": {
                        "target_x": target_x,
                        "target_y": target_y,
                        "max_speed_mps": 0.5,
                        "duration_s": 5.0,
                    },
                }
            ]
        else:
            calls = _calls_for_prompt(system, user)
        return json.dumps({"tool_calls": calls})
