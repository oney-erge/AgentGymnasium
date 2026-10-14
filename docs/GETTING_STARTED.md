# Setup, providers, and automation

Start with the root launcher described in the [README](../README.md). This guide covers manual setup, model connections, automation, and migration from Agentarium. Commands run from the repository root.

## Launcher and migration details

Every launcher accepts the same actions: `doctor`, `repair`, `docker`, `logs`,
and `stop`. Docker binds the UI to loopback and persists run data in a named
volume. You can double-click `run.bat` on Windows or `run.command` on macOS, and
use `.\run.ps1` to stay in PowerShell.

Setup checks disk space, serializes concurrent installs, and retries temporary
network failures up to three times. If it cannot finish, see
`.setup/install.log` for the persistent failure record.

The project was renamed from Agentarium to AgentGymnasium. The old names still work: the `agentarium`
command runs `agentgymnasium`, `AGENTARIUM_*` environment variables are read when the matching
`AGENTGYMNASIUM_*` one is not set, and an existing `runs/agentarium.db` keeps being used until
`runs/agentgymnasium.db` exists. With Docker, run data lived in a volume named for the old service
(`<project>_agentarium-runs`); the new service uses `<project>_agentgymnasium-runs`, so copy the data over
if you want to keep it.

To run things yourself:

```bash
uv sync --all-groups                 # install Python + deps
uv run agentgymnasium serve --open       # start the server, open the browser
```

To rebuild the web UI (only needed if you change the frontend; requires Node
20.19+ or 22.12+):

```bash
cd frontend && npm install && npm run build
```

`make run`, `make serve`, `make ui`, `make test`, and `make lint` wrap the same
commands.


## Model connections

- **LLM providers.** `mock` (offline, deterministic), `localdeploy`, and any
  OpenAI-compatible endpoint. Connection probes are short; generation calls have
  configurable timeouts and retry/backoff, and surface structured errors
  (auth / rate-limit / server / timeout / malformed). Tune via env vars:
  `AGENTGYMNASIUM_LLM_TIMEOUT_S` (default 120), `AGENTGYMNASIUM_LLM_RETRIES` (default 2),
  `AGENTGYMNASIUM_LLM_BACKOFF_S` (default 0.5).

### Headless runs and sweeps

The UI and automation use the same schemas and run pipeline:

```bash
uv run agentgymnasium run --config path/to/launch.yaml --seed 42
uv run agentgymnasium sweep --matrix path/to/experiment.yaml
```

Both commands print machine-readable JSON. Sweep cells remain ordinary durable
runs, so their replays open in Studio.

### Physical / ROS 2 gateway

Physical Lab always includes an offline mock rover. A real robot-side gateway
can be registered without adding ROS dependencies to the AgentGymnasium server:

```bash
AGENTGYMNASIUM_ROS2_GATEWAY_URL=http://robot-gateway:8080
AGENTGYMNASIUM_ROS2_GATEWAY_TOKEN=robot-side-secret
AGENTGYMNASIUM_OPERATOR_KEY=human-arming-secret
uv run agentgymnasium serve
```

Real-device arming also requires the operator key in the UI. AgentGymnasium only
sends bounded `drive_to` and `stop` actions; the robot-side gateway must enforce
its own local watchdog, actuator limits, collision avoidance, and physical
emergency stop. **AgentGymnasium is not a certified safety controller.** See
[`docs/EMBODIMENT.md`](EMBODIMENT.md).

### OpenAI API key

For OpenAI-compatible hosted models, put your key in a repo-root `.env` file:

```bash
OPENAI_API_KEY=sk-...
```

The backend loads that file automatically. The Setup screen shows a masked
preview such as `sk-********1234`, uses the env key when the API-key field is
blank, and does not save the real key into `runs/workspace_config.json`.


## Development

```bash
uv run ruff check .            # lint
uv run pytest                  # backend tests
cd frontend && npm run build   # type-check + build the UI; Node 20.19+ or 22.12+
npm --prefix frontend run lint # frontend lint

# Browser UI diagnosis — drives the Studio and Setup screens in headless Chromium
uv run python -m playwright install chromium   # one-time browser download
AGENTGYMNASIUM_VISUAL_TESTS=1 uv run pytest backend/tests/test_visual_playwright.py

# Optional live OpenAI smoke checks (normal tests stay offline)
AGENTGYMNASIUM_LIVE_OPENAI_TESTS=1 uv run pytest backend/tests/test_openai_live_smoke.py
```

CI runs lint + tests + the frontend build on every push and PR. Backend changes
must keep all three gates green and ship with tests (use the `mock` provider so
tests need no network). Playwright lets you smoke-test the side-view renderer,
tool-call log, and scorecard against a live local server — UI tests skip cleanly
if its browser isn't installed. Conventions and architecture invariants live in
[`CLAUDE.md`](../CLAUDE.md).
