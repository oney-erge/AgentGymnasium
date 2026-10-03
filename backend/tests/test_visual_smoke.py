"""Opt-in visual smoke tests: each scenario's mock run actually RENDERS (the
Phaser canvas mounts with a non-zero size) when loaded through the real Studio
page in a real browser.

This is a smoke test, not pixel-diff visual regression — pixel baselines are
flaky and need constant re-baselining. The substantive "does this scenario
look like the right challenge" check (right kinds, no foreign ones) is a pure
data-level test with no browser dependency:
``test_runner.py::test_challenge_kinds_do_not_leak_across_scenarios``, which
runs on every ``pytest``. This file only catches "the page crashed / the
canvas never mounted" regressions.

Skipped by default — spins up a live server + a Chromium browser (needs
``uv run python -m playwright install chromium``), which is slower and less
hermetic than the rest of the suite. Run explicitly with:

    AGENTGYMNASIUM_RUN_UI_SMOKE=1 uv run pytest backend/tests/test_visual_smoke.py
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
import uvicorn

from agentgymnasium.core.env import env

pytestmark = pytest.mark.skipif(
    not env("RUN_UI_SMOKE"),
    reason="opt-in: set AGENTGYMNASIUM_RUN_UI_SMOKE=1 (needs `playwright install chromium`)",
)

_CHALLENGES = [
    ("bridge_builder", "island_cliff_small", ["create_body", "add_beam", "add_joint", "run_simulation"]),
    ("crawl_challenge", "hill_path", ["create_body", "add_joint", "add_motor", "run_simulation"]),
    ("sorter", "sorting_table", ["create_body", "add_ramp", "add_bin", "run_simulation"]),
    ("tiny_city_preview", "tiny_city_block", ["create_body", "run_simulation"]),
]


@pytest.fixture(scope="module")
def live_server():
    """Run the real FastAPI app on an ephemeral port, in-process (same module-
    level run storage as the test below), for the duration of this module."""
    from agentgymnasium.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("live server did not start in time")

    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize("preset,world,tools", _CHALLENGES)
def test_scenario_canvas_renders(live_server: str, preset: str, world: str, tools: list[str]) -> None:
    from agentgymnasium.agents.runner import run_single_attempt
    from agentgymnasium.core.schemas.setup import (
        AgentConfig,
        AgentsConfig,
        LaunchConfig,
        LLMProvider,
        ScenarioConfig,
        ToolsConfig,
        WorldConfig,
    )

    config = LaunchConfig(
        scenario=ScenarioConfig(preset=preset),
        world=WorldConfig(template=world),
        agents=AgentsConfig(
            participants=[AgentConfig(id="a", name="Builder", provider=LLMProvider.mock)]
        ),
        tools=ToolsConfig(enabled=tools),
    )
    result = asyncio.run(run_single_attempt(config))
    assert result.trace_run_id is not None

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 900, "height": 700})
            page.goto(f"{live_server}/studio/{result.trace_run_id}", wait_until="networkidle")
            canvas = page.locator("canvas").first
            canvas.wait_for(state="attached", timeout=5000)
            box = canvas.bounding_box()
            assert box is not None, f"{preset}: canvas never mounted"
            assert box["width"] > 0 and box["height"] > 0, f"{preset}: canvas has zero size"
        finally:
            browser.close()
