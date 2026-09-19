# Fixed drive wheel and separate steering wheel

Native USB through the board's OTG connector is the only controller transport.
Use one cable. This firmware does not start Wi-Fi.
The motor watchdog runs independently from serial input/output.

This controller uses the confirmed GOOUUU ESP32-S3-CAM wiring: GPIO14 RPWM,
GPIO47 LPWM, GPIO13 MG90S steering, GPIO41/42 encoder inputs. It leaves the
existing one-shot combined test untouched. GPIO14/47 are never driven together.
The current robot is shown in [reference photos](../reference/calibration.md).

The firmware boots with zero motor output and the servo at its 90-degree neutral
pulse. It accepts newline JSON over the native USB CDC interface (the host uses 115200 baud as a nominal setting).
Limits are 30% signed duty, 20 degrees of servo offset, a 30 deg/s servo slew,
and a 300 ms motor watchdog. Positive steering offset lowers the commanded servo angle from 90 degrees
(90 minus offset in the known test's angle convention), **not** a
measured chassis turn or measured wheel angle. Encoder ticks are raw; steering,
wheel circumference, counts/revolution and stopping distance remain uncalibrated.
The steering link can have a non-linear ratio; no distance or yaw is promised.

Build without uploading:

```sh
uv tool run --from platformio platformio run -d robot/steering
```

The USB-only build was flashed and tested: 400 stopped telemetry samples over 20 seconds,
then both drive directions through the agent skill/bridge/firmware at 30% duty for
0.65 seconds. Both commands completed and disarmed. Zero-drive steering to +5 and
-5 degrees completed, but recentering caused another USB disconnect. macOS logged
USB Serial hardware connection loss; the ESP32 uptime stayed continuous. Recovery
verified 60 samples at zero duty, centered servo command and supervision off.
See [validation/wired.json](validation/wired.json). This does not establish the
cause of USB loss or calibrate distance/heading. Resolve the intermittent link
before sustained operation. The bridge closes control on serial errors or 500 ms
without valid telemetry and never replays movement after reconnection.
For future flashing, prepare for a bench test with the driven wheel lifted
and the steering linkage free through the test range. Use the same external
regulated servo supply/common ground setup as the verified hardware test.

After this stopped-by-default firmware is installed, start a local bridge:

```sh
uv run --project be python -m htn_backend.agent.motion.transport.serial_bridge \
  /dev/cu.usbmodem101 --supervise
```

Do not connect this bridge to the old automatic startup-test firmware: opening
serial may reset that firmware and rerun its boot-time motor sequence. The bridge
uses an explicit port, checks `single_steer_v1` identity, binds only to loopback,
and allows one controller. Without `--supervise`, commands remain disarmed. The
flag is a human supervision grant, not a model/controller performance setting.
Ctrl-C closes the bridge; firmware command expiry independently stops the motor.

### Badge supervision

Instead of `--supervise`, the hacker badge can hold the supervision grant. Its AUTO mode
(`badge/README.md`) streams armed packets at 20 Hz; the bridge tells the firmware it is
supervised only while those packets are fresh (300 ms) and an agent controller is connected:

```sh
export HTN_BADGE_TOKEN=$(openssl rand -hex 12)
uv run --project be python -m htn_backend.agent.motion.transport.serial_bridge \
  /dev/cu.usbmodem101 --badge-port 8794
```

Point the badge at the laptop (serial console): `url ws://<laptop-ip>:8794/?token=<token>`.
The badge endpoint only grants or withdraws supervision and forwards E-STOP; its drive,
arm and winch fields are ignored, so it cannot move the robot through the bridge. Badge
silence, a disconnect, leaving AUTO or disarming withdraws supervision, which stops the
motor and interrupts an agent move within about 300 ms. A badge E-STOP (B, or any button
while the agent drives) latches in firmware; re-arming the badge does not clear it. Reset
the board, keeping in mind that opening serial can also reset it. `--supervise` and
`--badge-port` are mutually exclusive. The controller endpoint remains loopback-only.
Checked with the host-compiled firmware protocol fixture
(`be/tests/agent/transport/test_badge_supervision.py`), not yet on the physical badge and robot.

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

The current build enables native hardware USB CDC (`ARDUINO_USB_CDC_ON_BOOT=1`,
board USB mode 1). TTL no longer carries the application console. The Mac port
name can change; identify the Espressif USB device rather than assuming its
suffix. If no port appears for initial flashing, hold BOOT, tap/release RST,
then release BOOT. Native-USB validation is in [validation/native-usb.json](validation/native-usb.json).
