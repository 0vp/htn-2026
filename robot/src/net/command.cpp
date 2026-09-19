#include "command.h"

#include <ArduinoJson.h>

namespace {

float unit(JsonVariantConst v) {
  const float x = v | 0.0f;
  return x > 1 ? 1 : (x < -1 ? -1 : x);
}

}  // namespace

bool parseCommand(const uint8_t *payload, size_t length, Command &out) {
  if (length > 1024) return false;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) return false;
  if (doc["type"] != "command") return false;

  Command c;
  c.seq = doc["seq"] | 0u;
  // A packet that doesn't say it is safe is treated as a stop.
  c.estop = doc["estop"] | true;
  c.armed = doc["armed"] | false;
  c.driveLeft = unit(doc["drive"]["left"]);
  c.driveRight = unit(doc["drive"]["right"]);
  c.arm[0] = doc["arm"]["shoulder"] | 0.0f;
  c.arm[1] = doc["arm"]["elbow"] | 0.0f;
  c.arm[2] = doc["arm"]["wrist"] | 0.0f;
  for (int i = 0; i < 3; i++) {
    const int w = doc["winch"][i] | 0;
    c.winch[i] = w > 0 ? 1 : (w < 0 ? -1 : 0);
  }
  out = c;
  return true;
}
