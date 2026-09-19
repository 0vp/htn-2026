#include <Arduino.h>

#include "actuators/arm.h"
#include "actuators/drive.h"
#include "actuators/winches.h"

namespace {

constexpr uint32_t CONTROL_MS = 10;  // 100 Hz actuator loop
uint32_t lastControl = 0;

}  // namespace

void setup() {
  Serial.begin(115200);
  // Outputs first, so every motor pin is driven low before anything else runs.
  drive::begin();
  winches::begin();
  arm::begin();
  lastControl = millis();
}

void loop() {
  const uint32_t now = millis();
  if (now - lastControl >= CONTROL_MS) {
    const float dt = (now - lastControl) / 1000.0f;
    drive::update(dt);
    arm::update(dt);
    winches::update(dt);
    lastControl = now;
  }
}
