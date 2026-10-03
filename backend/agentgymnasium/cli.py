import argparse
import asyncio
import json
import pathlib
import socket
import sys
import threading
import time
import urllib.request

import uvicorn
import yaml


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentgymnasium")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the AgentGymnasium server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    # Reload is OFF by default: the file-watcher can tear down live runs when
    # artifacts are written under runs/. Developers opt in with --reload.
    serve.add_argument("--reload", action="store_true", default=False)
    serve.add_argument("--no-reload", dest="reload", action="store_false")
    serve.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="Open the app in your browser once the server is ready",
    )

    run = sub.add_parser("run", help="Run one LaunchConfig headlessly")
    run.add_argument("--config", required=True, help="LaunchConfig JSON or YAML path")
    run.add_argument("--seed", type=int, help="Override world/model sampling seed")

    sweep = sub.add_parser("sweep", help="Run an ExperimentSpec matrix headlessly")
    sweep.add_argument("--matrix", required=True, help="ExperimentSpec JSON or YAML path")
    return parser


def _read_data(path_value: str) -> dict:
    path = pathlib.Path(path_value)
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one object")
    return value


async def _headless_run(config_path: str, seed: int | None) -> dict:
    from agentgymnasium.core.schemas.setup import LaunchConfig, LaunchState
    from agentgymnasium.services.orchestrator import run_manager
    from agentgymnasium.setup.validators import validate_launch_config

    config = LaunchConfig.model_validate(_read_data(config_path))
    if seed is not None:
        config.world.seed = seed
    validation = await validate_launch_config(config)
    if validation.state != LaunchState.ready:
        raise ValueError(
            f"{validation.state.value}: {', '.join(validation.missing)}"
        )
    run_id = await run_manager.create_run(config, provenance={"source": "cli"})
    finished: dict = {}
    async for event in run_manager.subscribe(run_id):
        if event.get("type") == "error":
            raise RuntimeError(str(event.get("detail") or "run failed"))
        if event.get("type") == "run_finished":
            finished = event
    return {"run_id": run_id, **finished}


async def _headless_sweep(matrix_path: str) -> dict:
    from agentgymnasium.core.schemas.experiment import ExperimentSpec
    from agentgymnasium.services.experiment_service import experiment_manager

    spec = ExperimentSpec.model_validate(_read_data(matrix_path))
    created = await experiment_manager.create(spec)
    finished = await experiment_manager.wait(created.id)
    if finished is None:
        raise RuntimeError("experiment disappeared")
    return {
        "experiment": finished.model_dump(mode="json"),
        "aggregates": [
            item.model_dump(mode="json")
            for item in (experiment_manager.aggregates(created.id) or [])
        ],
        "pairwise": [
            item.model_dump(mode="json")
            for item in (experiment_manager.pairwise(created.id) or [])
        ],
    }


def _port_in_use(host: str, port: int) -> bool:
    """True if ``host:port`` is already accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            return sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0
        except OSError:
            return False


def _open_when_ready(url: str, health_url: str) -> None:
    """Open ``url`` only once the server answers /api/health (max ~20s)."""

    def _wait_and_open() -> None:
        import webbrowser

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        webbrowser.open(url)
                        return
            except Exception:  # noqa: BLE001 - server not up yet; keep polling
                time.sleep(0.4)
        # Fallback: open anyway so the user isn't left without a window.
        webbrowser.open(url)

    threading.Thread(target=_wait_and_open, daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve" or args.command is None:
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8765)
        reload = getattr(args, "reload", False)

        if _port_in_use(host, port):
            print(
                f"\n  Port {port} is already in use — is AgentGymnasium already running?\n"
                f"  Open http://localhost:{port} in your browser, or stop the other\n"
                f"  process and try again (or pass a different --port).\n",
                file=sys.stderr,
            )
            raise SystemExit(1)

        if getattr(args, "open_browser", False):
            shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
            _open_when_ready(
                f"http://{shown}:{port}", f"http://127.0.0.1:{port}/api/health"
            )
        uvicorn.run("agentgymnasium.app:app", host=host, port=port, reload=reload)
    elif args.command == "run":
        try:
            result = asyncio.run(_headless_run(args.config, args.seed))
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            print(f"AgentGymnasium run failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(json.dumps(result, indent=2))
    elif args.command == "sweep":
        try:
            result = asyncio.run(_headless_sweep(args.matrix))
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            print(f"AgentGymnasium sweep failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
