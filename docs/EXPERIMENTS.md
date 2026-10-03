# Model experiments

AgentGymnasium evaluates models as controlled run matrices rather than as isolated
demos. Every cell is a normal persisted AgentGymnasium launch, so it keeps the
design, trace, score, tool calls, model interactions, launch config, and
provenance needed to audit or replay the result.

## Matrix

An experiment combines:

- one immutable base `LaunchConfig`;
- one or more provider/model variants;
- paired world/model seeds;
- one or more repeats.

The scheduler applies only the selected model variant and seed to each copied
base config. This keeps the task, world, tools, attempt budget, constraints, and
reward identical across models. A benchmark fingerprint derived from the
scenario, preset, world template, and tool schemas is stored with every run.

Experiments are intentionally bounded to 120 cells and run sequentially. That
keeps local endpoints and laptops usable and avoids changing results through
uncontrolled concurrency. Cancellation takes effect after the current cell.

## Statistics

The Experiments screen reports:

- sample count and success rate;
- mean score and sample standard deviation;
- normal-approximation 95% confidence interval;
- mean model latency and total tokens;
- pairwise comparisons on matching `(seed, repeat)` cells;
- paired win/tie/loss counts, mean score delta, and its 95% interval.

Small samples should be read as smoke evidence, not as a definitive leaderboard.
Use several representative tasks, enough paired seeds, and repeats when model
sampling is non-deterministic. A confidence interval that includes zero does not
establish a score difference.

## Headless sweep

Create a YAML or JSON matrix:

```yaml
name: bridge-model-comparison
base_config:
  project_name: Bridge benchmark
  scenario:
    preset: bridge_builder
    objective: Carry the crate over the real gap.
    reward: bridge_transport
  world:
    template: island_cliff_small
    seed: 7
  agents:
    mode: single
    participants:
      - id: builder
        name: Builder
        provider: mock
        model: mock
  tools:
    enabled: [create_body, add_beam, add_joint, run_simulation, inspect_score]
  constraints:
    max_attempts: 3
    agent_turns_per_attempt: 3
models:
  - id: local-a
    label: Local model A
    provider: localdeploy
    model: model-a
    endpoint_url: http://127.0.0.1:8000/v1
  - id: hosted-b
    label: Hosted model B
    provider: openai_compatible
    model: model-b
    endpoint_url: https://example.invalid/v1
seeds: [7, 11, 42]
repeats: 2
```

Run it with:

```bash
uv run agentarium sweep --matrix experiment.yaml
```

The CLI prints the completed record, aggregates, and paired comparisons as JSON. API keys can be
supplied at runtime, but are excluded from Pydantic serialization and redacted
from launch/experiment artifacts.

## Inspecting evidence

Use History to select two to four attempt trace ids and open Compare. Compare
normalizes replay progress across different trace lengths and shows score
metrics, provider/model/seed, tokens, latency, and tool-call protocol side by
side. Studio's Model Inspector exposes each persisted prompt/result turn.

Experiment records live under `runs/experiments/`; ordinary run data is indexed
in `runs/agentarium.db` and stored under `runs/<trace_run_id>/`.
