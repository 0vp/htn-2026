# Robot base

Two-wheel differential base built from a ride-on ATV's motors and wheels on an aluminium-extrusion
frame. Everything from the earlier bases (TB6612 bench rig, single-steer firmware, old calibration
and reference files) was removed on 2026-09-19; see git history if needed.

## Parts

| Part | Notes |
|---|---|
| GOOUUU ESP32-S3-CAM | Controller. Use the **TTL** USB-C port (CH340, `/dev/cu.usbserial-*`). Camera unused. |
| 2 × 12 V brushed DC motors + gearboxes | From the ride-on ATV, one per wheel. |
| 2 × BTS7960 / IBT-2 (43 A) | One H-bridge per motor. |
| 4 × IR obstacle-avoidance modules | Digital outputs. Active level and 3.3 V safety not yet verified. |
| 12 V battery + inline fuse | Motor power only. |
| Laptop | Rides centred on the deck; runs the scripts and is the calibration sensor (camera). |

## Wiring

| Signal | Left BTS7960 | Right BTS7960 |
|---|---|---|
| R_EN | GPIO4 | GPIO15 |
| L_EN | GPIO5 | GPIO16 |
| RPWM | GPIO6 | GPIO17 |
| LPWM | GPIO7 | GPIO18 |
| VCC (logic) | ESP32 5V | ESP32 5V |
| GND | common | common |

Power: battery + → fuse → both B+; battery − → both B−; M+/M− → that side's motor. Battery
negative, driver grounds and ESP32 ground are common. Never power a motor from the ESP32.

IR sensors (top view as reported by the hardware team; physical left/right not yet measured):

```text
GPIO41   GPIO2
GPIO42   GPIO1     <- wheel end
```

Firmware reports them as `ir_raw` in the order `[GPIO2, GPIO42, GPIO1, GPIO41]` (IR1..IR4).

## Firmware (`src/`)

Stopped by default. Newline JSON at 115200 baud:

- `{"type":"supervise","enabled":true}` — required before any motion.
- `{"type":"command","armed":true,"estop":false,"motors":{"left":0.2,"right":0.2}}` — raw duty,
  |duty| ≤ 0.6. Must repeat within 300 ms (watchdog). `estop:true` latches until reset.
- Telemetry every 50 ms: `drivetrain:"bts7960_diff_v2"`, motors, `ir_raw`, flags.

Safety behaviour: PWM is zero before enables rise; RPWM and LPWM are never driven together; a
direction change rests at zero for 250 ms; duty ramps at 1.5/s; stop drops all PWM and enables.

Flash (motor battery disconnected or wheels lifted):

```sh
uvx --from platformio pio run -t upload --upload-port /dev/cu.usbserial-10
```

## Scripts (`scripts/`, run with `be/.venv/bin/python`)

| Script | Purpose |
|---|---|
| `calibrate.py PORT` | Floor calibration (`--signs`, `--mins` skip steps already known) using the laptop camera as a visual gyro. Writes `calibration.json`. |
| `drive.py PORT` | One app: arrow-key driving plus the WebSocket (`ws://…:8793`) for the iOS app, the badge remote (`badge/`) and the agent. Keyboard wins; `[` `]` trim live and save. Protocol in its docstring. |
| `base.py` | Shared serial link; applies calibration (sign, swap, per-wheel minimum duty and gain). |
| `sense.py` | Camera yaw estimator. |

The MacBook's accelerometer/gyro is not readable without root on macOS, so calibration uses the
camera: yaw from horizontal image shift, forward/back from image scale change. It yields wheel
direction, minimum moving duty, left/right trim and spin rate in deg/s. It does **not** yield
metric speed; measure distance with a tape if that is needed.

## Agent architecture (Codex runs on this laptop)

Three layers, following the usual split in robot stacks (slow "deliberative" planner on top,
fast reflexes at the bottom, as in three-layer architectures, ROS 2 nav/control, SayCan and
Code-as-Policies style skill APIs): the planner may be slow or remote, but it only ever calls
short, bounded skills, and everything safety-critical lives next to the motors.

| Layer | Runs on | Does |
|---|---|---|
| World + speech | Cloud VM | Phone streams, map/scene, speech-to-text, room tool APIs, turn queue |
| Agent (Codex) | This laptop | Reasoning with your `codex login`; calls cloud room tools over HTTPS and motion skills locally |
| Skills | This laptop (`drive.py`, `agent/embodied`) | Route planning around obstacles, measured moves, calibration, keyboard override, command lease |
| Reflexes | ESP32 firmware | 300 ms watchdog, ramp, reversal pause, E-STOP latch |

Flow: phone speech → cloud transcribes and queues the finalized turn → the laptop worker
(`be/src/htn_backend/agent/worker.py`) long-polls `POST /v1/agent/jobs/claim`, runs Codex
locally, drives through `ws://127.0.0.1:8793`, and posts the answer to
`/v1/agent/jobs/{id}/result` → the phone speaks it. Motion never crosses the internet, so
network jitter cannot stutter or strand a move. Auth is the shared secret in
`scripts/.robot_token` (gitignored) / `/etc/htn/robot.env` on the VM.

`sh drive.sh` starts all of it and opens a Terminal window showing Codex's live log
(`robot/agent.log`). If no worker is polling, the server falls back to its own Codex
(`be/deploy/codex/install.sh`) and drives through the cloud relay that `drive.py` dials.

The agent's tools are `look`, `scan`, `go_to`, `approach`, `path`, `room_map`, `recall` and
`stop` (see `agent/harness.md`). The base is treated as a round body 80 cm across with the phone
at its centre. The agent is blocked while a human holds an arrow key (`owner: human`), after an
E-STOP, or if `drive.py` is not running.

## Calibration status (2026-09-19)

Front = the big drive-wheel end. The drivers were labelled from the other end, so
`calibration.json` has `swap: true` with signs left -1 / right +1 (floor driving test).

Measured on the floor by `calibrate.py --camera-faces front` after the rear casters were fixed
(2026-09-19 23:40), in `scripts/calibration.json`:

- Signs/swap: confirmed by both the camera run and the arrow-key driving test.
- Minimum duty: wheel-end-left driver 0.14, other 0.11 (first duty that turned the robot, minus 0.03).
- Trim: the "left" driver (physically the right wheel, from the front) runs at gain ~0.71;
  straight-run drift went from +3.0 to +0.8 deg per 0.6 s pulse. Readings are noisy (+-1.5 deg);
  fine-tune by eye with `[` `]` in `drive.py`.
- Spin at level 0.3: about +53 / -57 deg/s (camera yaw, assumed 54 deg HFOV, includes ramp).
- Not measured: metric speed.

## Measured vs assumed

- Measured: firmware identity, telemetry and IR reads over TTL after flashing (2026-09-19).
- Assumed: camera HFOV ≈ 54° (scales the deg/s figures only).
