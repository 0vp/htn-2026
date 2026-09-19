# Wi-Fi steering controller

The steering firmware starts stopped and runs both its own secured access point
and an optional saved 2.4 GHz Wi-Fi connection. The network name is
`HTN-Robot-XXXX`. A random per-device password is stored on the ESP32, not in Git.
The same password pairs the local controller and protects setup/supervision.

## Connect

1. Power the ESP32 from suitable USB power; keep motor power on the motor driver.
2. Join the robot access point. Read its initial pairing details over serial with
   `{"type":"wifi_info"}`; no motor command is needed.
3. Open `http://192.168.4.1`. Username: `robot`; password: the pairing password.
4. Enter a 2.4 GHz Wi-Fi network or compatible phone hotspot on the setup page.
   Credentials are stored only on the board. Captive-portal/enterprise networks
   are not supported by this small provisioner. The access point stays available.
5. The status page shows `network.station_ip`; use that address when your laptop
   is on the same network. `http://htn-robot.local` may also resolve there.

The local agent uses `HTN_ROBOT_URL=ws://<robot-address>:81` and
`HTN_ROBOT_TOKEN=<pairing-password>`. Keep secrets in your local environment.
The WebSocket uses the existing `single_steer_v1` command/telemetry contract, so
no USB bridge is necessary. Only one authenticated controller can connect.
Joining an AP alone does not expose a local robot directly to GCP.

## Supervision and stopping

Connect the controller first, then click **Enable supervision** on the setup
page. Keep that page visible while supervising. Its grant expires in two seconds
if renewals stop; renewals cannot resurrect an expired grant. The page never
sends movement commands. STOP disables supervision immediately. A disconnected
controller must reconnect and receive a new explicit supervision grant.

The 300ms motor command lease remains active. When a Wi-Fi command expires, the
supervision grant is also revoked. The actuator task runs independently of HTTP,
WebSocket and USB writes, so blocked network I/O does not prevent command expiry.
The existing 30% duty / 20-degree servo-offset limits and motor ramp remain.
Physical stop distance and steering geometry are still uncalibrated.

While a Wi-Fi controller owns the connection, serial movement/supervision packets
are ignored; local `wifi_info` remains available for pairing. Wi-Fi credentials
can be changed through the authenticated setup page. Firmware replacement/reboot
always starts disarmed, never replays the last command, and retains network setup.

## Validation

Build with `platformio run -d robot/steering`. Native tests cover motor expiry,
human-supervision expiry with ongoing commands, timer wraparound and rejection
of controller self-supervision. Software/native protocol checks are distinct from
an actual radio-link and charger-powered motion test.

The installed build passed three native executables, 28 Python checks, and setup-
page JavaScript syntax checking. After upload, 80 serial telemetry samples showed
zero motor output and supervision disabled, with the access point address present.
Actual Wi-Fi client traffic and charger-powered operation remain to be tested
after the user connects; see [validation/wifi.json](validation/wifi.json).
