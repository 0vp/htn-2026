# USB/steering investigation

The initial servo-power explanation was a hypothesis, not a measured diagnosis.
A subsequent test lost USB serial while the ESP32 kept running: uptime advanced
from 53,860 ms before the failure to 106,110 ms after reconnect, and its +5 degree
servo command survived. This does not show an ESP32 brownout/reset. It also does
not exclude a cable, USB-adapter supply, driver or host problem.

Opening the port with forced DTR/RTS false produced a boot banner in a comparison.
Normal line settings gave 100 telemetry frames in five seconds. The calibration
and bridge now keep normal line settings; the new session helper keeps one port
open across individually requested pulses. These changes avoid repeated setup,
but do not claim to fix the intermittent USB disconnect. ESPressif documents the
[reset-line behavior](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html).

The diagnostic firmware was built and uploaded successfully after one connection
failure. It reports uptime and reset reason. A zero-drive +3 degree command and
three-second idle checks before/after passed without resetting. A later move
toward +5 degrees timed out; negative steering and centering were not run after
the error. Reconnection yielded 61 consecutive stopped, unsupervised samples.

A subsequent 20-second idle check returned 400 telemetry samples, continuous
uptime and zero drive duty without a disconnect.

No additional wheel-drive command was issued during this investigation. Physical
steering direction, encoder scale and metric calibration remain unknown. All 28
calibration, transport and motion tests passed. These are software tests, not
proof of USB or mechanical reliability.

Use `session.py` instead of repeatedly invoking `pulse.py` for calibration. It
accepts one bounded JSON request per stdin line, disarms between requests and
ends on a failed request. It never reconnects and replays active movement.

## Unloaded follow-up

With the chassis inverted and wheels clear of the floor, the 0/-5/+5/0 degree
command sequence passed. Two 15% duty, 300ms drive pulses produced -61 and +62
encoder counts, respectively, returning to reported zero duty and disarmed state.
Uptime remained continuous and neither run reported a USB disconnect. See
[unloaded.json](unloaded.json). These tests do not measure actual steering angle
or establish which physical change removed the intermittent failure.
