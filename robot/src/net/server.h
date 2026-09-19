#pragma once

#include <Arduino.h>

#include "command.h"

/**
 * Access point and the WebSocket control server. Who may drive is decided in authority.h.
 * Telemetry is broadcast to every accepted client.
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
