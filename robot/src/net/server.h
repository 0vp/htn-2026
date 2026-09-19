#pragma once

#include <Arduino.h>

#include "command.h"

/**
 * Access point + WebSocket control server. Any number of clients (badge, dashboard) may
 * connect; the first to send an armed packet owns the robot until it disarms, disconnects
 * or goes silent. An E-STOP from any client stops everything and latches until an owner
 * re-arms. Telemetry is broadcast to every client.
 */
namespace server {

void begin();
void loop();

/** True while an owner is sending fresh armed packets: actuators may move. */
bool live();

/** The owner's latest command. Only meaningful while `live()`. */
const Command &command();

bool estopLatched();
uint8_t clientCount();

void broadcast(const char *json, size_t length);

}  // namespace server
