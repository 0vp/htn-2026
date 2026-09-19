#pragma once

#include <Arduino.h>

#include "telemetry.h"

struct Settings;

/**
 * Wi-Fi station plus a WebSocket client to the robot's control URL — the same socket the
 * dashboard streams to. The badge sends JSON command packets at 20 Hz and merges any
 * telemetry or pose JSON the robot sends back. The robot must stop if packets stop.
 */
namespace robotlink {

enum class Status : uint8_t { Unconfigured, JoiningWifi, Connecting, Silent, Open };

/** Starts the network task. */
void begin(const Settings &settings);

/** Hands new settings to the network task, which reconnects with them. */
void reconfigure(const Settings &settings);

/** Queues a packet; the network task sends the latest one. */
bool send(const char *json, size_t length);

Status status();
const char *statusText();
/** Socket open and the robot heard from in the last 0.6 s: safe to stay armed. */
bool isOpen();
String localIp();
int wifiRssi();
uint32_t sentCount();
uint32_t receivedCount();

/** Milliseconds since anything arrived from the robot, or UINT32_MAX if nothing has. */
uint32_t silenceMs();

const Telemetry &telemetry();

/** Wall-clock ms once SNTP has synced (matching the dashboard's Date.now()), else uptime. */
uint64_t timestampMs();

}  // namespace robotlink
