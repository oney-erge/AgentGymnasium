# Embodiment and physical agents

AgentGymnasium's embodiment layer is a narrow, high-level contract shared by its
deterministic mock rover and an optional robot-side ROS 2 gateway:

```text
model → typed drive_to/stop → host safety supervisor → adapter
      ← normalized observation ← robot or simulation
```

It deliberately does not expose raw motors, PWM, arbitrary ROS topics, shell
commands, or filesystem/network tools to a model.

## Safety state machine

Every device starts `disarmed`.

```text
disarmed -- explicit confirmation --> armed
armed -- disarm --> disarmed
armed -- operator/watchdog --> emergency_stopped
emergency_stopped -- explicit reset --> disarmed
```

Arming returns an in-memory control token. Actions, heartbeats, and normal
disarming require that token. The watchdog latches the emergency stop when
heartbeats expire. Action validation rejects targets outside the geofence,
speeds above the device limit, excessive durations, non-finite values, and
actions while disarmed. Emergency stop remains callable without a token.

For `real` and `hardware_in_the_loop` devices, arming and emergency-stop reset
additionally require the `AGENTGYMNASIUM_OPERATOR_KEY`. If the variable is missing,
hardware-backed arming is disabled. Tokens and operator keys are never included
in device/event reads or episode artifacts.

These controls reduce software risk; they do not make a general-purpose
computer a safety PLC. A real robot must independently enforce a local
communications watchdog, velocity/force/actuator limits, collision avoidance,
work-cell interlocks, and a physical emergency stop.

## LLM embodied episodes

An armed device can run a bounded model episode from Physical Lab or:

```http
POST /api/embodiments/{device_id}/episodes
X-AgentGymnasium-Control-Token: ...
```

The episode:

1. optionally resets a non-real adapter to a comparable start state;
2. records a normalized observation;
3. asks the selected model for at most one `drive_to` or `stop` tool call;
4. executes it through the safety supervisor;
5. observes again and repeats up to the turn limit;
6. scores progress to the declared target and persists all model interactions,
   action receipts, and observations.

Hardware-backed devices never software-reset. Establishing identical physical
start states between model trials remains an operator/test-fixture responsibility.

Episode artifacts are written to `runs/embodiment-episodes/`.

## ROS 2 gateway registration

Set:

```bash
AGENTGYMNASIUM_ROS2_GATEWAY_URL=http://robot-gateway:8080
AGENTGYMNASIUM_ROS2_GATEWAY_TOKEN=robot-side-secret
AGENTGYMNASIUM_ROS2_DEVICE_ID=ros2-rover
AGENTGYMNASIUM_ROS2_DEVICE_LABEL="Lab Rover"
AGENTGYMNASIUM_ROS2_MODE=real
AGENTGYMNASIUM_OPERATOR_KEY=human-arming-secret
```

Only URL and gateway token are required for registration. The mode defaults to
`real`.

The gateway contract is:

| Method | Path | Meaning |
| --- | --- | --- |
| `GET` | `/v1/observation` | Return an `EmbodimentObservation`. |
| `POST` | `/v1/actions` | Accept one typed `EmbodimentAction`; return the next observation. |
| `POST` | `/v1/emergency-stop` | Immediately stop and latch robot-side motion. |
| `POST` | `/v1/reset` | Logical reset for non-real/HIL fixtures only. |

Requests carry `Authorization: Bearer <AGENTGYMNASIUM_ROS2_GATEWAY_TOKEN>`. The
gateway should map the normalized messages to stable ROS 2 topics,
services/actions, and `ros2_control` controllers. It must reject unsupported
actions and apply its own limits before touching actuators.

## API surface

- `GET /api/embodiments`
- `GET /api/embodiments/events`
- `GET /api/embodiments/{id}/observation`
- `POST /api/embodiments/{id}/arm`
- `POST /api/embodiments/{id}/heartbeat`
- `POST /api/embodiments/{id}/actions`
- `POST /api/embodiments/{id}/episodes`
- `POST /api/embodiments/{id}/disarm`
- `POST /api/embodiments/{id}/emergency-stop`
- `POST /api/embodiments/{id}/reset-emergency-stop`
