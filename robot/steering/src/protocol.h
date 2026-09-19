#pragma once
#include <ArduinoJson.h>
#include <cstring>
#include "control.h"

inline void handlePacket(const char* data, size_t size, SteeringControl& control, uint32_t now) {
  JsonDocument doc;
  if (size > 512 || deserializeJson(doc, data, size)) { control.stop(); return; }
  const char* type = doc["type"] | "";
  if (strcmp(type, "supervise") == 0) {
    control.supervise(doc["enabled"] == true);
    return;
  }
  if (strcmp(type, "command") != 0) { control.stop(); return; }
  if (doc["estop"] | true) {
    control.command(false, true, 0, 0, now);
    return;
  }
  const bool armed = doc["armed"] == true;
  if (armed && (!doc["drive"]["duty"].is<float>() ||
                !doc["drive"]["steering_deg"].is<float>())) {
    control.stop(); return;
  }
  control.command(armed, doc["estop"] | true, doc["drive"]["duty"] | 0.f,
                  doc["drive"]["steering_deg"] | 0.f, now);
}
