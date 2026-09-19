# Lessons for a replacement robot base

## Mistakes to avoid

- We initially modeled one powered steering wheel, then learned that the real
  chassis has a fixed powered wheel and a separate servo-steered small wheel.
  Confirm the mechanism from photographs and the builder before selecting
  kinematics. Four swivel casters are not four spherical ball supports.
- We suggested insufficient servo power before measuring the failure. Some USB
  drops occurred while ESP32 uptime remained continuous. A historical brownout
  reset reason does not identify the cause of a later disconnect. Separate
  observations, hypotheses and verified causes in every report.
- Our early 15% duty, 300 ms pulses with a duty ramp did not reproduce the user's
  reported working 80/255 motor test. Compare PWM frequency, pulse mapping,
  duty ramp, time at target duty and load before concluding the hardware cannot
  move. Do not remove bounds or restore automatic boot movement to match a test.
- Forcing DTR/RTS low caused a reset in one comparison. Keep tested line states
  and a persistent connection; opening serial can reset a controller. Identify
  installed firmware before opening a board with a motion-on-boot test sketch.
- The bridge formerly let its command receiver outlive a failed telemetry task.
  It now cancels command reception, attempts stop/disarm, and closes the client
  on serial failure or 500 ms without valid telemetry. Firmware independently
  expires active motor commands after 300 ms. A disconnected wire can prevent
  stop delivery; host cleanup is not a substitute for the controller watchdog.
- Changing to Wi-Fi did not diagnose the intermittent wired fault. Wi-Fi has now
  been removed at the user's request. Change one variable per experiment.

## Current evidence, not a completed calibration

The USB-only run passed 400 idle telemetry samples over 20 seconds and two
opposite 30% duty, 0.65-second commands through the agent/bridge/ESP32 path.
Steering +5 and -5 degree commands passed; recentering then lost USB. macOS
logged USB Serial hardware connection loss while ESP32 uptime remained
continuous. Recovery verified zero duty, centered servo command and supervision
off. See [wired evidence](../steering/validation/wired.json).

Encoder changes show rotation/count activity, not calibrated chassis travel.
Reported servo angle is a pulse command, not measured wheel angle. A successful
stop receipt establishes zero electrical duty, not measured stopping distance.
Cable, connector, adapter supply, electrical interference and host USB faults
remain hypotheses. The root cause has not been isolated.

## Procedure when changing the base

1. Record actual drive/steering contacts, caster type, actuator model, pin map,
   encoder wiring, power sources, controller revision and USB port labels.
2. Preserve the known test's parameters as a reference. Install stopped-on-boot
   control with bounded commands and a watchdog independent of networking/I/O.
3. Validate idle communications first, then unloaded motor-only and servo-only
   commands, then short loaded commands with clearance and a slack tether.
   Log uptime, reset reason, applied duty, encoder counts and host USB events.
4. If USB drops, stop the experiment and verify recovery without replaying the
   old command. Substitute one cable/host port at a time. Isolate servo power
   using a verified regulated supply and common signal ground if needed;
   establish the board's power wiring before combining supplies.
5. Measure loaded wheel circumference, encoder counts per revolution, actual
   steering angles, contact geometry, phone-to-base transform and stopping
   distance. Repeat forward/reverse and left/right trials. Keep unknowns null;
   do not fit metric calibration from unreadable tape or tiny image shifts.
6. Re-run parser, transport-loss, watchdog, stale-feedback and stop tests, then
   verify the full agent path on the real controller. Publish limitations with
   results; simulation and software tests do not establish physical reliability.

## Two USB-C connectors on this board

The supplied close-up shows GOOUUU ESP32-S3-CAM, with the connected port labeled
TTL and the empty port labeled OTG. TTL is our observed CH340 USB-to-UART path.
The earlier firmware set `ARDUINO_USB_CDC_ON_BOOT=0` and used UART `Serial`.
The current build enables native hardware USB CDC on OTG instead.
OTG is the native USB path; switching control to it requires a deliberately
configured and tested firmware/host-port change, not just moving the cable.
Espressif documents native USB on GPIO19/20 and CDC support in its
[USB device guide](https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html).

We have not verified this board revision's USB power isolation or simultaneous
supply support. The photo does not establish that. Do not describe two connected
USB cables as double power or a confirmed fix. Use one port for now; a native
USB-only experiment could isolate the external serial bridge without Wi-Fi,
but cannot establish or fix a shared power issue on its own.

A subsequent native-USB build was flashed through `/dev/cu.usbmodem101`.
It passed a 20-second stopped telemetry check and +5/-5/0 degree zero-drive
steering without the previous disconnect. This is preliminary comparative
evidence, not proof of the TTL fault's cause or long-term OTG reliability.
See [native USB results](../steering/validation/native-usb.json).

The user subsequently supplied a different two-wheel layout, recorded in
[current-base.json](current-base.json). Do not flash either the old single-steer
firmware or the legacy `robot/src` differential firmware without confirming the
new controller and pin map. The legacy differential code targets another board.
Approximate footprint is not wheel-contact spacing; neither supplies encoder
scale. Unequal wheel loading should be measured, not hidden by an assumed trim.
