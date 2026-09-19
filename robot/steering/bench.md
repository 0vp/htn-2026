# Fixed drive wheel and separate steering wheel

This controller uses the confirmed GOOUUU ESP32-S3-CAM wiring: GPIO14 RPWM,
GPIO47 LPWM, GPIO13 MG90S steering, GPIO41/42 encoder inputs. It leaves the
existing one-shot combined test untouched. GPIO14/47 are never driven together.
The current robot is shown in [reference photos](../reference/calibration.md).

The firmware boots with zero motor output and the servo at its 90-degree neutral
pulse. It accepts newline JSON over the USB serial adapter at 115200 baud.
Limits are 30% signed duty, 20 degrees of servo offset, a 30 deg/s servo slew,
and a 300 ms motor watchdog. Positive steering offset means a commanded left
servo offset (90 minus offset in the known test's angle convention), **not** a
measured chassis turn or measured wheel angle. Encoder ticks are raw; steering,
wheel circumference, counts/revolution and stopping distance remain uncalibrated.
The steering link can have a non-linear ratio; no distance or yaw is promised.

Build without uploading:

```sh
uv tool run --from platformio platformio run -d robot/steering
```

No automatic reset/upload or live motor test has been run by the agent. Flash
this firmware only when ready for the bench test, with the driven wheel lifted
and the steering linkage free through the test range. Use the same external
regulated servo supply/common ground setup as the verified hardware test.

After this stopped-by-default firmware is installed, start a local bridge:

```sh
uv run --project be python -m htn_backend.agent.motion.transport.serial_bridge \
  /dev/cu.usbserial-10 --supervise
```

Do not connect this bridge to the old automatic startup-test firmware: opening
serial may reset that firmware and rerun its boot-time motor sequence. The bridge
uses an explicit port, checks `single_steer_v1` identity, binds only to loopback,
and allows one controller. Without `--supervise`, commands remain disarmed. The
flag is a human supervision grant, not a model/controller performance setting.
Ctrl-C closes the bridge; firmware command expiry independently stops the motor.

Use `HTN_ROBOT_URL=ws://127.0.0.1:8793` for the laptop agent. Its room still uses
`HTN_SERVER_URL`. `robot_status` must report the expected drivetrain and fresh
supervision before `drive_base` can send a bounded command. A call provides
`duty`, `steering_deg` and `seconds` (maximum two). There is no turn-in-place tool.
Old left/right packets are rejected, not translated into this mechanism.
Arm/winch actions remain unavailable because this sketch has no arm drivers.

A stalled skill cannot keep moving through the link's 20Hz heartbeat: active
commands have a separate 250 ms host lease. Firmware expiry covers a dead bridge.
Zero duty is electrical command feedback, not proof the chassis has stopped.
This is a supervised bench integration, not autonomous collision avoidance.
