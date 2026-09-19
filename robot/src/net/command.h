#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * One operator command, as sent by the dashboard (fe/src/control/store.ts packet()) and the
 * badge (badge/src/control/control.cpp). `goal` (go-to on the LiDAR map) is not handled here:
 * the base has no pose estimate of its own.
 */
struct Command {
  uint32_t seq = 0;
  bool estop = false;
  bool armed = false;
  float driveLeft = 0;
  float driveRight = 0;
  float arm[3] = {0, 0, 0};
  int8_t winch[3] = {0, 0, 0};
};

/** Parses a `{"type":"command",...}` frame. Returns false for anything else. */
bool parseCommand(const uint8_t *payload, size_t length, Command &out);
