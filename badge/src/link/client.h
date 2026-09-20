#pragma once

#include <Arduino.h>

struct Settings;

/**
 * Wi-Fi station and the control client that dials the laptop running robot/scripts/drive.py
 * (`ws://<laptop-ip>:8793/?token=...`, started with `--host 0.0.0.0 --token ...`).
 *
 * The badge owns no motors: it is the same kind of client the iOS app is, so the D-pad and the
 * laptop's arrow keys reach the base through one path. Packets go out at 20 Hz because drive.py
 * drops an app command after 0.5 s, and drive.py's keyboard always outranks us. drive.py accepts
 * one app client at a time, so the dashboard cannot be connected at the same time.
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
 * Publishes the operator's intent for the next packets. `silent` withholds them entirely, which
 * is how AUTO lets the cloud agent's own commands through drive.py untouched; a change of
 * `armed`, `estop` or `silent` is still flushed so a stop always lands.
 */
void command(bool armed, bool estop, float linear, float angular, bool silent);

const Telemetry &telemetry();
/** Milliseconds since the last telemetry frame, or UINT32_MAX if none has arrived. */
uint32_t telemetrySilenceMs();

}  // namespace robotlink
