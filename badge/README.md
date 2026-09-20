# badge — handheld remote for the robot base

Firmware that turns the Hack the North 2026 hacker badge (ESP32-C3, 2.0" ST7789, D-pad) into a
wireless remote for the differential base. It drives nothing itself: it dials the laptop running
`robot/scripts/drive.py` over Wi-Fi and sends the same logical command the laptop's arrow keys
produce, so the D-pad and the arrow keys reach the base through one code path.

```text
badge D-pad ──ws──> drive.py (laptop) ──usb serial──> ESP32-S3 ──> BTS7960 ×2 ──> wheels
                       ^                                   arrow keys outrank the badge
```

## Run it

Start `drive.py` on the laptop so it listens beyond loopback (it refuses a non-loopback host
without a token):

```sh
sh drive.sh --host 0.0.0.0 --token SECRET
```

Then, on the badge's USB serial console at 115200 (`pio device monitor`):

```text
wifi <ssid> <password>
url ws://<laptop-ip>:8793/
token SECRET
status
```

Settings live in NVS and survive reflashing. The token is appended to the URL as `?token=`, so a
URL that already carries one is left alone. Only `ws://` works — TLS on the C3 is not worth it for
a link that never leaves the LAN, and `drive.py` serves plain WebSocket.

## Controls

| Input | Action |
|---|---|
| **START** (hold 1 s) | Arm, and clear the badge's own E-STOP |
| **START** (tap while armed) | Disarm |
| **B** | Stop and disarm — the same soft stop as `drive.py`'s space bar |
| **B** (hold 1 s) | Latching E-STOP. **The base firmware holds it until the board is reset.** |
| **HOME** | Switch mode: DRIVE ⇄ AUTO |
| DRIVE | D-pad drives while held (ramped, diagonals mix); **A** cycles the limit 25/50/75/100 % |
| AUTO | Hold START to let the cloud agent drive; the badge only watches. Any button stops it. |

The screen shows the stick, the base's two wheel duties from telemetry, which controller
`drive.py` is currently obeying, the live trim, and the link state.

## Protocol

The badge is an ordinary `drive.py` app client (`robot/scripts/drive.py` → `wheels()`), sending
at 20 Hz because `drive.py` drops an app command after 500 ms:

```json
{"type":"command","seq":42,"t":1789000000000,"armed":true,"estop":false,
 "source":"badge","drive":{"linear":0.30,"angular":-0.15}}
```

`+ linear` is forward and `+ angular` turns left, matching `drive.py`, which mixes them into
`(linear - angular, linear + angular)` and then applies `calibration.json`. Values are logical
−1..1 *before* calibration; `MAX_LEVEL` is 0.6 to match `drive.py`'s `--limit`, so nothing is
renormalised on the far side. Telemetry comes back on the same socket at 20 Hz and is shown on
screen; frames over 2 KB are ignored.

Three consequences worth knowing:

- **The laptop's arrow keys always win.** `drive.py` prefers the keyboard over any app client, so
  a hand on the laptop overrides the badge without disconnecting it.
- **`drive.py` accepts one local client at a time**, so the badge and the iOS app/dashboard cannot
  both be connected to `:8793`. The cloud relay is a separate socket, so the cloud agent still gets
  through.
- **AUTO goes silent on purpose.** `drive.py` keeps one command per connection and obeys the first
  that is still within its 500 ms lease, so a badge that kept transmitting while supervising would
  be racing the cloud agent for the base. In AUTO the badge sends nothing until it intervenes, and
  a change of arm or E-STOP state is always flushed so a stop still lands.

If the link drops, the badge stops transmitting and `drive.py`'s 500 ms lease plus the base
firmware's 300 ms watchdog stop the motors.

## Build and flash

```sh
pip install platformio
pio run -t upload
```

If upload can't connect, hold START while plugging in USB for download mode.
A full backup of the stock badge firmware is kept off-repo (it contains the badge's credentials);
restore it with `esptool.py write_flash 0x0 full_flash_4MB.bin`.

Other console commands: `help` lists them all. `buttons` prints raw shift-register bytes,
`lcd invert 0|1` fixes inverted colours, `mode drive|auto` switches the screen, and `shot` dumps
the frame. To save a screenshot (opening the port restarts the badge):

```sh
python badge/tools/badge_shot.py /dev/cu.usbmodem2101 screen.png
```

## Hardware map

Read from the stock firmware (GPIO matrix over the built-in USB-JTAG, plus its `esp_lcd` config in
the disassembly), then confirmed on device:

| Function | GPIO |
|---|---|
| LCD SCLK / MOSI / CS / DC / RESET | 1 / 10 / 2 / 0 / 4 (backlight always on) |
| 74HC165 LOAD / CLK / QH | 20 / 21 / 7 (buttons pull low; bit order A, B, Home, Down, Left, Right, Up, Aux1) |
| START (BOOT strap) | 9 |
| WS2812B ×6 | 3 (unused) |
| I2C SDA / SCL (SC7A20H accelerometer, MFRC522 NFC — unused) | 5 / 6 |

The badge drives no motors, so GPIO 3, 5 and 6 are free again.
