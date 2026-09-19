#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * One operator command, as sent by the dashboard (fe/src/control/store.ts packet()) and the
 * badge (badge/src/control/control.cpp). `goal` (go-to on the LiDAR map) is not handled here:
 * the base has no pose estimate of its own.
 *
 * `source` says who sent it: "badge", "agent", or anything else (the dashboard) as a human.
 * `auto` marks the badge's AUTO mode: the badge supervises and the agent drives.
 */
enum class Source : uint8_t { Human, Badge, Agent };

struct Command {
  Source source = Source::Human;
  bool autoMode = false;
  uint32_t seq = 0;
  bool estop = false;
  bool armed = false;
  float driveLeft = 0;
  float driveRight = 0;
  bool hasArm = false;  // the arm only moves when a command carries angles
  float arm[3] = {0, 0, 0};
  int8_t winch[3] = {0, 0, 0};
};

/** Parses a `{"type":"command",...}` frame. Returns false for anything else. */
bool parseCommand(const uint8_t *payload, size_t length, Command &out);
