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

After a server restart, an interrupted experiment remains stopped until you
choose **Resume queued cells**. Completed cells stay intact. An in-flight cell
is marked failed and is never retried automatically because a provider request
may already have run or incurred a charge. Supply keys again for queued model
variants if required; credentials are not saved. Older records without the
in-flight checkpoint cannot be safely resumed and remain available to inspect.
The API also accepts `POST /api/experiments/{id}/resume` with an `api_keys`
object keyed by queued model variant ID; sending this request explicitly starts
the remaining cells.

## Statistics

The Experiments screen reports:

- sample count and success rate;
- mean score and sample standard deviation;
- Student-t 95% confidence interval when at least two scores are available;
- mean model latency and total tokens;
- pairwise comparisons on matching `(seed, repeat)` cells;
- paired win/tie/loss counts, mean score delta, and its 95% interval.

The interval assumes independent observations and an approximately normal mean;
repeated runs using the same seed may not be independent. For more than 30
degrees of freedom the 30-df critical value is used conservatively. No interval
is reported for fewer than two observations or pairs. Samples smaller than five
are preliminary and should be read as smoke evidence, not a definitive leaderboard.
Use several representative tasks, enough paired seeds, and repeats when model
sampling is non-deterministic. A confidence interval that includes zero does not
establish a score difference.

## Headless sweep

Try the versioned [offline bridge comparison](examples/bridge-comparison-v1.yaml)
first:

```bash
uv run agentgymnasium sweep --matrix docs/examples/bridge-comparison-v1.yaml
```

It prints each trial, per-variant aggregates, and paired comparisons as JSON.
Both variants use scripted mock tool calls: they demonstrate the pipeline and
are not evidence of real model performance. For a real comparison, copy the
file, configure the model providers and endpoints, and record the model versions
and any provider costs alongside the resulting experiment.

An offline Windows run of this exact pack completed six cells. Both scripted
variants scored 80 on seeds 7, 11, and 42, so all three paired comparisons
were ties. This is an example of the output, not a model leaderboard.

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
uv run agentgymnasium sweep --matrix experiment.yaml
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
in `runs/agentgymnasium.db` and stored under `runs/<trace_run_id>/`.
