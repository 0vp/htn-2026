# badge — handheld robot controller

Firmware that turns the Hack the North 2026 hacker badge (ESP32-C3, 2.0" ST7789, D-pad) into a
wireless remote for the robot. It speaks the dashboard's protocol: JSON `command` packets at
20 Hz over a WebSocket (`fe/src/control/store.ts` → `packet()`), so the robot firmware serves one
control socket for both the dashboard and the badge.

## Controls

| Input | Action |
|---|---|
| **B** | E-STOP — latches, disarms, zeroes all motion |
| **START** (hold 1 s) | Arm and clear E-STOP; only while the robot link is up |
| **START** (tap while armed) | Disarm |
| **HOME** | Next mode: DRIVE → ARM → WINCH → AUTO |
| DRIVE | D-pad drives (arcade mix, ramped); **A** cycles speed limit 25/50/75/100 % |
| ARM | Left/Right picks shoulder/elbow/wrist; Up/Down moves 45°/s within limits; **A** re-centres |
| WINCH | Left/Right picks winch 1–3; Up reels in (-1), Down pays out (+1) while held |
| AUTO | Hold START to let the agent drive (the badge only supervises); **any button** is an E-STOP |

LEDs: orange pulse = no link, blue = linked + safe, green = armed, red pulse = E-STOP.
The badge disarms itself if the link drops. The robot must still stop on its own if
packets stop arriving (the dashboard makes the same assumption).

## Packet

```json
{"type":"command","seq":42,"t":1789000000000,"estop":false,"armed":true,
 "drive":{"left":0.25,"right":0.5},"arm":{"shoulder":10,"elbow":-5,"wrist":0},
 "winch":[0,-1,0],"goal":null,"source":"badge"}
```

`t` is Unix ms once SNTP syncs, else badge uptime; use `seq` for ordering. Anything the robot
sends back on the socket is merged as telemetry (`packVolts`, `rpm`, `winchPos`, `limits`,
`rssi`, `pose`) and shown on screen; messages over 4 KB (LiDAR point batches) are ignored.

## Setup

Open a serial monitor at 115200 (`pio device monitor`) and type:

```
wifi htn-robot <password>
url ws://192.168.4.1:81/
status
```

The robot (`robot/`) runs the `htn-robot` access point; its password is in the robot's git-ignored
`src/secrets.h`. Any other network works too, as long as the badge can reach the robot over IPv4.

Settings live in NVS and survive reflashing. `help` lists the other commands: `buttons` prints
raw shift-register bytes, `lcd invert 0|1` fixes inverted colours, `mode drive|arm|winch` switches
the screen, and `shot` dumps the frame. To save a screenshot (opening the port restarts the badge):

```sh
python badge/tools/badge_shot.py /dev/cu.usbmodem2101 screen.png
```

## Build and flash

```sh
pip install platformio
pio run -t upload
```

If upload can't connect, hold START while plugging in USB for download mode.
A full backup of the stock badge firmware is kept off-repo (it contains the badge's credentials);
restore it with `esptool.py write_flash 0x0 full_flash_4MB.bin`.

## Hardware map

Read from the stock firmware (GPIO matrix over the built-in USB-JTAG, plus its `esp_lcd` config in
the disassembly), then confirmed on device:

| Function | GPIO |
|---|---|
| LCD SCLK / MOSI / CS / DC / RESET | 1 / 10 / 2 / 0 / 4 (backlight always on) |
| 74HC165 LOAD / CLK / QH | 20 / 21 / 7 (buttons pull low; bit order A, B, Home, Down, Left, Right, Up, Aux1) |
| START (BOOT strap) | 9 |
| WS2812B ×6 | 3 |
| I2C SDA / SCL (SC7A20H accelerometer, MFRC522 NFC — unused) | 5 / 6 |
