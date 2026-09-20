#pragma once

#include <Arduino.h>

struct Settings;

/**
 * The control client that reaches the laptop running robot/scripts/drive.py, over either
 * transport (`link usb` / `link wifi` on the console):
 *
 *   USB   the same JSON packets as lines on this console, read by `drive.py --badge <port>`.
 *         Nothing wireless is involved, so the radio stays off.
 *   Wi-Fi dials `ws://<laptop-ip>:8793/?token=...` (drive.py started `--host 0.0.0.0 --token ...`).
 *
 * The badge owns no motors: it is the same kind of client the iOS app is, so the D-pad and the
 * laptop's arrow keys reach the base through one path. Packets go out at 20 Hz because drive.py
 * drops an app command after 0.5 s, and drive.py's keyboard always outranks us. drive.py accepts
 * one local client at a time, so the dashboard cannot be connected to the same socket.
 */
namespace robotlink {

enum class Status : uint8_t { Unconfigured, JoiningWifi, Dialing, Linked };

/** Last telemetry frame drive.py pushed back, at 20 Hz (drive.py -> App.report). */
struct Telemetry {
  bool valid = false;
  uint32_t at = 0;
  float left = 0;          // Raw duty the base applied, after calibration.
  float right = 0;
  bool estop = true;
  bool supervised = false;
  char source[12] = "";    // "keyboard", "app" or "idle" — who drive.py is obeying.
  char owner[8] = "";      // "human", "agent" or "none".
  float trimLeft = 1.0f;
  float trimRight = 1.0f;
};

void begin(const Settings &settings);

/** Hands new Wi-Fi or URL settings to the network task, which redials with them. */
void reconfigure(const Settings &settings);

Status status();
const char *statusText();
String localIp();
int wifiRssi();
bool linked();

/**
 * Publishes the operator's intent for the next packets. drive.py keeps one command per
 * connection, so a disarmed badge clears only its own and never cancels the cloud agent's.
 * A change of `armed` or `estop` is repeated a few times, so a stop always lands.
 */
void command(bool armed, bool estop, float linear, float angular);

const Telemetry &telemetry();
/** Milliseconds since the last telemetry frame, or UINT32_MAX if none has arrived. */
uint32_t telemetrySilenceMs();

/** Hands a `{...}` console line to the USB transport; the console owns the serial reader. */
void feedTelemetry(const String &line);

}  // namespace robotlink
