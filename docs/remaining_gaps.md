# Remaining gaps

This is the current backlog after the model-evaluation, iterative-agent,
constraint-enforcement, multi-agent, and embodiment work. Historical plans live
under `docs/archive/`; shipped details are in `IMPROVEMENTS.md`.

## Physical deployment

| Priority | Gap | What “done” means |
| --- | --- | --- |
| High | The ROS 2 side is a documented HTTP contract and AgentGymnasium adapter, not a reference ROS 2 package. | Ship a small gateway package with message/action definitions, `ros2_control` integration, a robot-local watchdog, launch files, and a fake-hardware CI fixture. |
| High | Host-side safety is not a certified hardware safety system. | Hardware risk assessment, work-cell interlocks, physical E-stop validation, robot-local limits, authenticated/TLS network boundary, operator roles, and deployment-specific acceptance tests. |
| High | Physical comparisons cannot guarantee identical starting state. | A task fixture with fiducials/pose reset, calibration record, environment version, operator checklist, and paired-trial randomization. Never silently “reset” a real robot in software. |
| Medium | Embodiment session events are in memory; episode results are JSON files. | Durable append-only audit rows with operator/device/task ids, clock synchronization, calibration hash, checksums, and export tooling. |
| Medium | Only planar `drive_to` and `stop` are exposed. | Add task-specific high-level skills (grasp, place, inspect) one at a time, each with typed limits, simulation/shadow implementation, failure recovery, and robot-side enforcement. |

## Evaluation science

| Priority | Gap | What “done” means |
| --- | --- | --- |
| High | The UI reports normal-approximation 95% intervals even for small samples. | Student-t/bootstrap intervals, explicit minimum-sample warnings, effect sizes, multiple-task aggregation, and raw CSV/Parquet export. |
| High | Experiments stop after restart rather than resuming. | Persist a credential-free schedule, resume queued cells only after operator reauthorization, and record environment/provider versions. |
| Medium | The scheduler is sequential only. | Resource-aware workers with per-endpoint concurrency/rate limits while preserving paired scheduling and deterministic local runs. |
| Medium | Model capability negotiation is shallow. | Detect native-tool, seed, usage, streaming, and structured-output support per endpoint; persist negotiated capability/version metadata. |
| Medium | No canonical benchmark suite spans simulation and embodiment. | Versioned task packs with golden mock traces, normalized scores, fixed tool contracts, calibration metadata, and a release process. |

## Simulation and sim-to-real

| Priority | Gap | What “done” means |
| --- | --- | --- |
| High | Pymunk2D and CitySim are the live engines; `pybullet3d` remains unsupported. | A real 3D adapter producing the same trace contract, with renderer support and deterministic benchmark tests. |
| High | There is no MuJoCo/Gazebo digital-twin path or domain randomization. | Calibrated robot/world assets, sensor/latency/noise randomization, shadow-mode comparison, and quantified transfer error. |
| Medium | Collision safety preflight catches exact agent-body stacking, not future contact risk. | Engine-level swept collision checks, stability envelopes, force/impulse limits, and task-specific safety scoring. |
| Medium | Motor energy is a comparable estimate, not measured joules. | Engine/controller power telemetry and calibrated real-device energy measurements with units and sensor provenance. |
| Low | Slide/spring joint geometry is still partly hardcoded. | Derive limits/rest length from bodies or expose validated tool parameters. |

## Runtime and product

| Priority | Gap | What “done” means |
| --- | --- | --- |
| Medium | CPU simulation and some artifact/SQLite work remain synchronous in the server process. | Worker-process execution, cancellation, timeouts, backpressure, and integration tests for WebSocket ordering. |
| Medium | Experimental tools (`add_sensor`, controllers, mutation/repair helpers, collision groups) are honestly disabled rather than implemented. | Implement only with observable semantics, chokepoint validation, trace representation, scoring use, UI evidence, and tests. |
| Medium | Provider prompts/results can be sensitive even though API keys are redacted. | Configurable retention, prompt redaction policies, encrypted-at-rest option, deletion/export controls, and documented threat model. |
| Low | `AgentConfig.context_window` and per-agent `max_attempts` remain backward-compatible schema fields but do not control runtime. | Remove them in a versioned schema migration or define and enforce unambiguous semantics. |
| Low | Screenshot/WebM capture remains browser-side; GIF/MP4 is absent. | Optional encoder/transcode worker with explicit resource limits and artifact lifecycle. |

## Visual fidelity

| Priority | Gap | What “done” means |
| --- | --- | --- |
| Medium | The polished renderer is still procedural 2.5D rather than a true 3D scene. | Resolve the PyBullet/Three.js product call, then add authored 3D assets, real lights, camera orbit, occlusion, and GPU performance budgets without breaking trace-only replay. |
| Low | Decorative city traffic/pedestrians are trace-derived ambience, not CitySim actors. | Add explicit actor events and paths when moving people/vehicles become part of simulation or scoring; keep purely decorative ambience honest until then. |
| Low | Browser visual CI checks deterministic screenshots and distinct themes, not strict cross-platform pixel baselines. | Adopt platform-pinned image baselines only if the maintenance cost is justified; keep structured scene assertions and uploaded artifacts as the default. |

## Test gaps

- Robot gateway contract tests against a fake ROS 2 hardware component.
- Watchdog and emergency-stop timing tests across real process/network failure.
- Property/fuzz tests for provider tool arguments and embodiment actions.
- Experiment recovery/cancellation tests across server restart.
- Browser interaction tests for Experiments, Compare, Model Inspector, and Physical Lab
  controls (the calibrated Physical Lab map and visual catalog now have screenshot coverage).
- Load tests for long traces and large experiment histories.
