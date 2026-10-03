"""CLI argument parsing for `agentgymnasium serve` (Step 25.5 — easy launch).

We test the parser, not uvicorn: the launcher passes `--no-reload --open`, so
those must parse correctly, and the defaults must stay backwards-compatible.
"""

import socket

from agentgymnasium.cli import _build_parser, _port_in_use


def test_serve_launcher_flags():
    args = _build_parser().parse_args(["serve", "--no-reload", "--open"])
    assert args.command == "serve"
    assert args.reload is False
    assert args.open_browser is True
    assert args.host == "127.0.0.1"
    assert args.port == 8765


def test_serve_defaults():
    args = _build_parser().parse_args(["serve"])
    # Reload is OFF by default (the watcher can tear down live runs).
    assert args.reload is False
    assert args.open_browser is False


def test_serve_reload_opt_in():
    args = _build_parser().parse_args(["serve", "--reload"])
    assert args.reload is True


def test_serve_custom_host_port():
    args = _build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_port_in_use_detection():
    # A free, unbound port is not in use.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert _port_in_use("127.0.0.1", free_port) is False

    # A bound, listening port is detected as in use.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        bound_port = listener.getsockname()[1]
        assert _port_in_use("127.0.0.1", bound_port) is True


def test_headless_run_and_sweep_flags():
    run = _build_parser().parse_args(["run", "--config", "cfg.yaml", "--seed", "42"])
    assert run.command == "run"
    assert run.config == "cfg.yaml"
    assert run.seed == 42

    sweep = _build_parser().parse_args(["sweep", "--matrix", "matrix.json"])
    assert sweep.command == "sweep"
    assert sweep.matrix == "matrix.json"
