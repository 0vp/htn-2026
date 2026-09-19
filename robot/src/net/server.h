#pragma once

#include <Arduino.h>

#include "command.h"

/**
 * Access point + WebSocket control server. Any number of clients (badge, dashboard) may
 * connect; the first to send an armed packet owns the robot until it disarms, disconnects
 * or goes silent. An E-STOP from any client stops everything and latches until an owner
 * re-arms. Telemetry is broadcast to every client.
 *
 * `loop()` runs on the Arduino loop task and can block for seconds on a dead client's TCP
 * write, so the actuator task only ever reads state through `snapshot()`, which is safe
 * from another task and applies the failsafe timeout itself.
 */
namespace server {

void begin();
void loop();

/**
 * Copies the owner's latest command. Returns true only while an owner is sending fresh
 * armed packets (actuators may move); false on E-STOP, no owner, or a stale command.
 */
bool snapshot(Command &out);

bool estopLatched();
uint8_t clientCount();

void broadcast(const char *json, size_t length);

}  // namespace server
