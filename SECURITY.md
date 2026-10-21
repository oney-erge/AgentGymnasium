# Security Policy

## Scope

AgentGymnasium is a local evaluation and simulation environment for one person on their own
machine. The server listens on `127.0.0.1` by default (`agentgymnasium serve --host` changes that)
and the provided Docker Compose file publishes the port on `127.0.0.1` only. It has no user
accounts, TLS, or rate limiting. Do not expose it to a network or the internet.

It is **not a certified robot safety controller**. The Physical Lab boundary and any ROS 2 gateway
you connect must independently enforce local watchdogs, actuator limits, collision avoidance, and an
emergency stop. Physical Lab control actions require a per-session control token
(`X-AgentGymnasium-Control-Token`), which protects the session, not the hardware.

## What it does with your data

- **Model prompts.** Each agent turn sends the challenge, tool results, and design state to the
  model endpoint you configure: LocalDeploy or another local server stays on your machine, an
  OpenAI-compatible cloud endpoint does not. The default `mock` agent sends nothing.
- **API keys.** A key typed into the Setup screen is saved in plain text in
  `runs/workspace_config.json` and is included in the Setup API response and in **Export JSON**.
  `runs/` is ignored by Git, but an exported configuration is an ordinary file you can share by
  accident. Prefer the "OpenAI-Compatible (env key)" provider with the key in an environment
  variable, and check any exported JSON before you share it. Run configurations stored with each
  run do not include the key.
- **Run history.** Attempts, traces, scorecards, and model interactions (prompts, latency, token
  counts) are stored under `runs/` (a local SQLite database and artifacts). Delete the folder to
  remove them.

## Known limits

| Limit | Why it matters |
|---|---|
| No authentication on the API | Anyone who can reach the port can read configurations (including a saved key), start runs, and read history. |
| Plain HTTP | Nothing on the connection is protected if it crosses a network. |
| Plain-text key storage | See above; there is no secret store. |
| Agent-chosen designs | Agents act only through validated tools inside the simulation, but their output is model-generated and should not be passed to other systems unreviewed. |

## Reporting a vulnerability

Use the **Report a vulnerability** button on the repository's Security tab if it is shown, instead
of opening a public issue.

If that button is not available, open a minimal issue asking for a private contact method. Do not
put exploit details, API keys, private prompts, or local paths in the public issue.

## Disclaimer

AgentGymnasium is provided without warranty under the [Apache License 2.0](LICENSE). Review the
code and configuration for your environment before connecting it to real hardware.
