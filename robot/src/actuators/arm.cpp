#include "arm.h"

#include <Arduino.h>

#include "../config.h"
#include "../pins.h"

namespace {

// 50 Hz on LEDC channels 4-6 (timers 2 and 3), 16-bit for fine pulse steps.
constexpr uint8_t FIRST_CHANNEL = 4;
constexpr uint32_t SERVO_HZ = 50;
constexpr uint8_t SERVO_BITS = 16;
constexpr float PERIOD_US = 1000000.0f / SERVO_HZ;
const int SIGNAL_PINS[3] = {pins::SERVO_SHOULDER, pins::SERVO_ELBOW, pins::SERVO_WRIST};

float current[3] = {0, 0, 0};
float target[3] = {0, 0, 0};
bool isAttached = false;

void writeJoint(int j) {
  const config::ServoCal &cal = config::SERVOS[j];
  float us = cal.neutralUs + cal.sign * current[j] * cal.usPerDegree;
  us = constrain(us, 500.0f, 2500.0f);
  ledcWrite(FIRST_CHANNEL + j, static_cast<uint32_t>(us / PERIOD_US * ((1u << SERVO_BITS) - 1)));
}

}  // namespace

namespace arm {

void begin() {
  // Servos stay unpowered-signal (no pulses) until the first command, so they don't jump
  // to neutral on boot while the arm may be resting somewhere else.
  for (int j = 0; j < 3; j++) {
    pinMode(SIGNAL_PINS[j], OUTPUT);
    digitalWrite(SIGNAL_PINS[j], LOW);
  }
}

void setTarget(const float degrees[3]) {
  for (int j = 0; j < 3; j++) {
    const config::ServoCal &cal = config::SERVOS[j];
    target[j] = constrain(degrees[j], static_cast<float>(cal.minDeg), static_cast<float>(cal.maxDeg));
  }
  if (isAttached) return;
  for (int j = 0; j < 3; j++) {
    ledcSetup(FIRST_CHANNEL + j, SERVO_HZ, SERVO_BITS);
    ledcAttachPin(SIGNAL_PINS[j], FIRST_CHANNEL + j);
    current[j] = target[j];
    writeJoint(j);
  }
  isAttached = true;
}

void update(float dt) {
  if (!isAttached) return;
  const float step = config::SERVO_DEG_PER_S * dt;
  for (int j = 0; j < 3; j++) {
    if (current[j] == target[j]) continue;
    const float diff = target[j] - current[j];
    current[j] = fabsf(diff) <= step ? target[j] : current[j] + (diff > 0 ? step : -step);
    writeJoint(j);
  }
}

float angle(int joint) { return current[joint]; }
bool attached() { return isAttached; }

}  // namespace arm
