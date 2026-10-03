"""Opt-in browser screenshots for the Setup and Studio surfaces.

Normal pytest runs skip this module. CI enables it with
AGENTGYMNASIUM_VISUAL_TESTS=1 and uploads the generated PNGs as artifacts.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from agentgymnasium.core.env import env
from tests.goldens import (
    bridge_builder_golden,
    city_builder_golden,
    crawl_challenge_golden,
    sorter_golden,
    tiny_city_golden,
)

pytestmark = pytest.mark.skipif(
    env("VISUAL_TESTS") != "1",
    reason="set AGENTGYMNASIUM_VISUAL_TESTS=1 to run browser visual checks",
)

PREVIEW_IMAGES = {
    "bridge-builder": "Bridge Builder",
    "city-builder": "City Builder",
    "crawl-challenge": "Crawl Challenge",
    "sorter": "Sorter",
    "custom-scenario": "Custom Scenario",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def artifact_dir() -> pathlib.Path:
    path = pathlib.Path(env("VISUAL_ARTIFACT_DIR", "visual-artifacts"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="module")
def live_server() -> str:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    backend = pathlib.Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(backend) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agentgymnasium.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=pathlib.Path(__file__).resolve().parents[2],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("visual test server exited before startup")
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception:  # noqa: BLE001 - server is still booting
            time.sleep(0.25)
    else:
        proc.terminate()
        raise RuntimeError("visual test server did not answer /api/health")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


_PREINSTALLED_CHROMIUM = "/opt/pw-browsers/chromium"


def _launch_chromium(p):
    # Prefer the environment's preinstalled Chromium (avoids a network fetch
    # when the pinned playwright version's expected revision isn't the one
    # baked into the image); fall back to playwright's own if absent.
    if pathlib.Path(_PREINSTALLED_CHROMIUM).exists():
        return p.chromium.launch(executable_path=_PREINSTALLED_CHROMIUM)
    return p.chromium.launch()


@pytest.fixture()
def page(live_server: str) -> Page:
    with sync_playwright() as p:
        browser = _launch_chromium(p)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(15_000)
        yield page
        browser.close()


def _assert_png(path: pathlib.Path) -> None:
    assert path.is_file()
    assert path.stat().st_size > 500


def test_setup_and_challenge_previews_have_visual_artifacts(
    page: Page,
    live_server: str,
    artifact_dir: pathlib.Path,
) -> None:
    page.goto(f"{live_server}/setup", wait_until="networkidle")
    expect(page.get_by_text("Simulation Setup")).to_be_visible()

    setup_path = artifact_dir / "setup-screen.png"
    page.screenshot(path=str(setup_path), full_page=True)
    _assert_png(setup_path)

    for image_name, label in PREVIEW_IMAGES.items():
        card = page.get_by_text(label).first
        expect(card).to_be_visible()
        img = page.locator(f'img[src$="{image_name}.png"]').first
        expect(img).to_be_visible()
        path = artifact_dir / f"preview-{image_name}.png"
        img.screenshot(path=str(path))
        _assert_png(path)


def test_studio_replay_has_visual_artifact(
    page: Page,
    live_server: str,
    artifact_dir: pathlib.Path,
) -> None:
    request = urllib.request.Request(
        f"{live_server}/api/runs",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        run_id = json.loads(resp.read().decode("utf-8"))["run_id"]

    page.goto(f"{live_server}/studio/{run_id}", wait_until="networkidle")
    expect(page.get_by_text("Replay Timeline")).to_be_visible()
    canvas = page.locator("canvas").first
    expect(canvas).to_be_visible()
    page.wait_for_timeout(800)

    studio_path = artifact_dir / "studio-replay.png"
    page.screenshot(path=str(studio_path), full_page=True)
    _assert_png(studio_path)


def test_visual_catalog_renders_distinct_seeded_themes(
    page: Page,
    live_server: str,
    artifact_dir: pathlib.Path,
) -> None:
    page.goto(f"{live_server}/visuals", wait_until="networkidle")
    expect(page.get_by_text("Renderer visual catalog")).to_be_visible()
    canvas = page.locator("canvas").first
    expect(canvas).to_be_visible()

    captures: list[bytes] = []
    style_select = page.get_by_label("Visual style")
    for style in ("realistic", "playful", "blueprint", "neon_lab"):
        style_select.select_option(style)
        page.wait_for_timeout(200)
        path = artifact_dir / f"visual-catalog-city-{style}.png"
        canvas.screenshot(path=str(path))
        _assert_png(path)
        captures.append(path.read_bytes())

    # Theme selection must change actual rendered pixels, not only the dropdown.
    assert len({payload for payload in captures}) == len(captures)


def test_physical_workspace_has_instrumented_visual_artifact(
    page: Page,
    live_server: str,
    artifact_dir: pathlib.Path,
) -> None:
    page.goto(f"{live_server}/physical", wait_until="networkidle")
    expect(page.get_by_text("Geofenced workspace")).to_be_visible()
    workspace = page.get_by_role("img", name="Calibrated workspace", exact=False)
    expect(workspace).to_be_visible()
    expect(page.get_by_text("TARGET", exact=True)).to_be_visible()
    expect(page.get_by_text("BATTERY", exact=True)).to_be_visible()

    path = artifact_dir / "physical-lab-workspace.png"
    workspace.screenshot(path=str(path))
    _assert_png(path)


# ── Self-eval: golden (known-good) designs, before/after screenshots ───────────
#
# These drive a verified solution to a challenge to its final frame and
# screenshot the canvas — the images a reviewer (human or an agent with vision)
# reads to judge "does this actually look like a bridge/city/sorted balls?"
# rather than trusting the score alone. See docs/CHALLENGE_OVERHAUL_PLAN.md.

GOLDEN_DESIGNS = {
    "bridge-builder": bridge_builder_golden,
    "city-builder": city_builder_golden,
    "sorter": sorter_golden,
    "crawl-challenge": crawl_challenge_golden,
    "tiny-city-preview": tiny_city_golden,
}


def _create_run(live_server: str, design, world, duration_seconds: float) -> str:
    payload = {
        "design": design.model_dump(mode="json"),
        "world": world.model_dump(mode="json"),
        "duration_seconds": duration_seconds,
    }
    request = urllib.request.Request(
        f"{live_server}/api/runs",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))["run_id"]


@pytest.mark.parametrize("challenge_id", sorted(GOLDEN_DESIGNS))
def test_golden_design_before_after_screenshots(
    challenge_id: str,
    page: Page,
    live_server: str,
    artifact_dir: pathlib.Path,
) -> None:
    design, world = GOLDEN_DESIGNS[challenge_id]()
    # Thirty simulated seconds captures the crawler at the finish and gives
    # bridge/sorter ample settle time. A much longer crawler replay can keep
    # driving after success because motors intentionally remain active.
    run_id = _create_run(live_server, design, world, duration_seconds=30.0)

    page.goto(f"{live_server}/studio/{run_id}", wait_until="networkidle")
    canvas = page.locator("canvas").first
    expect(canvas).to_be_visible()
    page.wait_for_timeout(500)
    page.locator("[data-hide-for-capture]").evaluate_all(
        "(elements) => elements.forEach((element) => element.style.display = 'none')"
    )

    before_path = artifact_dir / f"{challenge_id}-golden-before.png"
    canvas.screenshot(path=str(before_path))
    _assert_png(before_path)

    # Autoplay starts on load; pause it before seeking, or the play loop's own
    # frame-advance races the manual seek and the click gets overwritten.
    pause_button = page.get_by_role("button", name="Pause", exact=False)
    if pause_button.count() > 0:
        pause_button.first.click()
        page.wait_for_timeout(200)

    # Seek to the last replay tick (closest to the end of the trace).
    seek_buttons = page.locator('button[title^="Seek to"]')
    expect(seek_buttons.last).to_be_visible()
    seek_buttons.last.click()
    page.wait_for_timeout(500)

    after_path = artifact_dir / f"{challenge_id}-golden-after.png"
    canvas.screenshot(path=str(after_path))
    _assert_png(after_path)
