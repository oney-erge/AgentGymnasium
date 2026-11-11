"""Record a saved run's replay as a GIF: the follow camera, the crate's trail, the load glow.

    uv run agentgymnasium serve                     # in one terminal
    uv run --with pillow python scripts/record_demo.py RUN_ID docs/assets/demo.gif [--seconds 9]

It downloads the run's offline replay page from the server, opens it in a headless browser
(Microsoft Edge when installed, which draws on the real GPU), switches on the follow camera, plays
the replay and records the world view with the browser's screencast. The frames are kept in
.demo-frames with their timestamps, then paced in real time into a GIF with Pillow.
"""

from __future__ import annotations

import argparse
import base64
import bisect
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / ".demo-frames"
VIEW = {"width": 1280, "height": 760}
SCALE = 1.5  # screencast frames are 1920 x 1140


def record(server: str, run_id: str, seconds: float) -> list[tuple[float, str]]:
    page_file = FRAMES / "replay.html"
    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.glob("*.jpg"):
        old.unlink()
    with urllib.request.urlopen(f"{server}/api/exports/{run_id}/replay") as response:
        page_file.write_bytes(response.read())
    times: list[tuple[float, str]] = []
    with sync_playwright() as p:
        args = [f"--force-device-scale-factor={SCALE}"]
        try:
            browser = p.chromium.launch(channel="msedge", headless=True, args=args)
        except Exception:
            browser = p.chromium.launch(headless=True, args=args)
        page = browser.new_page(viewport=VIEW, device_scale_factor=SCALE, color_scheme="dark")
        page.goto(page_file.as_uri())
        page.get_by_title("Follow the payload").wait_for()
        page.wait_for_timeout(1500)
        page.get_by_title("Follow the payload").click()
        # The camera buttons and the view badge are for people using the page, not the clip.
        page.add_style_tag(content="[data-hide-for-capture] { display: none !important; }")
        cdp = page.context.new_cdp_session(page)

        stopped = False

        def frame(event: dict) -> None:
            if stopped:  # a frame still in flight after the recording ended
                return
            name = f"{len(times):05d}.jpg"
            (FRAMES / name).write_bytes(base64.b64decode(event["data"]))
            times.append((event["metadata"].get("timestamp", time.time()), name))
            cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})

        cdp.on("Page.screencastFrame", frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "everyNthFrame": 1})
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Play").click()
        page.wait_for_timeout(int(seconds * 1000))
        stopped = True
        cdp.send("Page.stopScreencast")
        browser.close()
    (FRAMES / "times.json").write_text(json.dumps(times))
    return times


def world_box(width: int, height: int) -> tuple[int, int, int, int]:
    """The world view in a frame: everything between the page header and the slider row."""
    top = round(118 * SCALE)
    bottom = height - round(56 * SCALE)
    return (round(17 * SCALE), top, width - round(17 * SCALE), bottom)


def make_gif(times: list[tuple[float, str]], out: Path, fps: int = 12, width: int = 880) -> None:
    starts = [t - times[0][0] for t, _ in times]
    end = starts[-1]
    images, durations, previous = [], [], None
    for k in range(int(end * fps) + 1):
        index = max(0, bisect.bisect_right(starts, k / fps) - 1)
        name = times[index][1]
        if name == previous:
            durations[-1] += round(1000 / fps)
            continue
        image = Image.open(FRAMES / name).convert("RGB")
        image = image.crop(world_box(*image.size))
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
        images.append(image)
        durations.append(round(1000 / fps))
        previous = name
    durations[-1] += 1500  # a beat on the last frame before the loop starts again
    # One palette from frames across the clip, so every frame maps onto the same colors.
    picks = [images[i * (len(images) - 1) // 3] for i in range(4)]
    sheet = Image.new("RGB", (picks[0].width, picks[0].height * len(picks)))
    for row, image in enumerate(picks):
        sheet.paste(image, (0, row * image.height))
    palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    frames = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"{out}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {out.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_id")
    parser.add_argument("out", type=Path)
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--seconds", type=float, default=9.0)
    args = parser.parse_args()
    times = record(args.server.rstrip("/"), args.run_id, args.seconds)
    make_gif(times, args.out)


if __name__ == "__main__":
    main()
