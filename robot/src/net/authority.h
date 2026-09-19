#pragma once

#include <stdint.h>

#include "command.h"

/**
 * Who may move the robot. Safe to read from the actuator task through `snapshot()`.
 *
 * - The robot boots in E-STOP. An E-STOP from any client latches and releases control.
 * - Humans (badge, dashboard): the first to arm owns the robot and clears the latch.
 * - AUTO: the badge, connected on the robot's own access point, sends armed `auto` packets
 *   as a supervisor heartbeat. Only while that heartbeat is fresh may an agent own the robot.
 *   An agent can never clear the E-STOP latch; losing supervision stops it within 300 ms.
 */
namespace authority {

enum class Role : uint8_t { None, Human, Agent };

struct Status {
  Role owner;
  bool supervised;
  bool latched;
};

/** `local` is true for clients on the robot's own access point. */
void onCommand(uint8_t client, bool local, const Command &c);
void onDisconnect(uint8_t client);

/** Releases a silent owner or an agent that lost supervision. Call from the network loop. */
void tick();

/** Copies the owner's command; true only while actuators may move. */
bool snapshot(Command &out);

Status status();

const char *roleName(Role role);

}  // namespace authority
