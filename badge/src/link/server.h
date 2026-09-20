#pragma once

#include <Arduino.h>

struct Settings;

/**
 * Wi-Fi station and the control server the agent's motion tools connect to
 * (`be/src/htn_backend/agent/motion/link.py` → `ws://<badge-ip>:81/?token=...`).
 *
 * The badge is now the robot controller: it speaks the same command and telemetry contract as
 * robot/steering (drivetrain `single_steer_v1`), so `drive_base`, `robot_status` and `stop`
 * work unchanged. Network clients may command motion but can never grant themselves
 * supervision: only the human at the badge does that by arming AUTO. An E-STOP latches until
 * a human re-arms here.
 */
namespace robotserver {

enum class Status : uint8_t { Unconfigured, JoiningWifi, Ready };

void begin(const Settings &settings);

/** Hands new Wi-Fi settings to the network task, which rejoins with them. */
void reconfigure(const Settings &settings);

Status status();
const char *statusText();
String localIp();
int wifiRssi();
uint8_t clientCount();
/** Milliseconds since the last command from a network client, or UINT32_MAX if none. */
uint32_t agentSilenceMs();

// --- control state, shared with the motor task ---

/** Copies the live drive command; true when the motor may run. */
bool snapshot(float &duty, float &steering);

/** The human at the badge grants or withdraws supervision by arming AUTO. */
void supervise(bool enabled);

/** Latches an emergency stop; only `clearEstop()` from a human button release clears it. */
void emergencyStop();
void clearEstop();

/** Manual driving from the badge's own D-pad, which outranks a network command. */
void setLocal(bool active, float duty, float steering);

bool estopLatched();
bool supervised();
/** "none", "human" (badge D-pad) or "agent" (network client). */
const char *owner();

}  // namespace robotserver
