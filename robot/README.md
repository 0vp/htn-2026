# robot — base controller firmware

For the confirmed fixed powered wheel + separate MG90S steering wheel on the
ESP32-S3, use [steering/bench.md](steering/bench.md). The root firmware below is
the earlier two-motor design and is not compatible with that chassis.

Runs on an **ELEGOO ESP32 (ESP-WROOM-32 DevKit)** and drives everything on the robot except
the camera. The **GOOUUU ESP32-S3-CAM** is a separate board that only streams video: its camera
uses 14 GPIOs, which left too few pins for the motors, encoders, servos, winches and end stops.
The two boards share nothing but the robot's Wi-Fi.

```text
 badge (ESP32-C3) ─┐                      ┌─ BTS7960 x2 → base motors (+ encoders)
                   ├─ Wi-Fi "htn-robot" ─ ELEGOO ESP32 ─ servos x3 (shoulder, elbow, wrist)
 dashboard (fe) ───┤   ws://192.168.4.1:81/ └─ TB6612FNG x2 → N20 winches x3 (+ end stops)
 ESP32-S3-CAM ─────┘   camera: http://<cam-ip>:81/stream
```

## Protocol

Clients send the dashboard's command packet (`fe/src/control/store.ts` → `packet()`) at 20 Hz;
the badge sends the same format. The robot broadcasts telemetry JSON at 5 Hz on the same socket
(`fe/src/telemetry/types.ts` fields), so the dashboard can use this URL for both `?control=` and
its telemetry source.

Safety rules:

- The robot boots in E-STOP. The first client to send `armed: true, estop: false` takes control;
  packets from other clients are ignored until it disarms, disconnects or is silent for 2 s.
- `estop: true` from **any** client stops everything and latches until an owner re-arms.
- No packet from the owner for 300 ms stops the base and winches immediately (the worm gears
  self-lock). Servos hold their last angle and only get pulses after the first armed command.
- `goal` (go-to on the LiDAR map) is ignored: the base has no pose estimate of its own.

## Wiring

| Signal | GPIO | Notes |
|---|---|---|
| BTS7960 R_EN + L_EN (both modules) | 12 | **10k pull-down required** (boot strap, keeps motors off) |
| Left BTS7960 RPWM / LPWM | 25 / 26 | forward / reverse, 20 kHz |
| Right BTS7960 RPWM / LPWM | 27 / 33 | forward / reverse, 20 kHz |
| Left encoder A / B | 34 / 35 | input-only: add 10k pull-ups to 3.3V if outputs are open collector |
| Right encoder A / B | 36 (VP) / 39 (VN) | same |
| Servo shoulder / elbow / wrist | 13 / 14 / 23 | signal only; power from the 6.0V rail |
| TB6612 STBY (both boards) | 2 | **10k pull-down**; the board's blue LED shows winches enabled |
| Winch 1 IN1 / IN2 | 4 / 16 | TB6612 PWMA/PWMB tied to 3.3V |
| Winch 2 IN1 / IN2 | 17 / 18 | |
| Winch 3 IN1 / IN2 | 19 / 21 | |
| Winch 1 / 2 / 3 end stops | 5 / 15 / 22 | both stops of a winch in parallel, switch to GND (COM + NO) |
| Pack voltage | 32 | 100k from pack+ / 27k to GND |

Grounds all common, as in the shopping list. Encoders powered from 3.3V. GPIO 0 (BOOT), 1 and 3
(USB serial) are left free.

End stops share one pin per winch, so the firmware tells them apart by the direction the winch
was moving. A stop already pressed at power-on can't be identified until the winch first moves.

## Build and flash

```sh
cp src/secrets.example.h src/secrets.h   # set ROBOT_AP_PASSWORD (8+ chars); git-ignored
pip install platformio
pio run -t upload && pio device monitor
```

Point the badge at the robot over USB serial: `wifi htn-robot <password>` then
`url ws://192.168.4.1:81/`. For the dashboard, join `htn-robot` and open
`?control=ws://192.168.4.1:81/`.

## Calibrate before driving hard

All in `src/config.h`, marked `CALIBRATE`:

1. `ENCODER_COUNTS_PER_REV` — the serial log prints raw encoder counts every 2 s; turn a wheel
   10 times by hand and divide. Until set, telemetry leaves out rpm and odometry.
2. `SERVOS` — neutral pulse, µs per degree and direction for each joint (defaults assume 270°
   servos centred at 1500 µs). Test with the arm unloaded.
3. `WINCH_TRAVEL_S` — seconds for a full in → out run.
4. `BATTERY_SCALE` — compare `pack` in the serial log with a multimeter.
