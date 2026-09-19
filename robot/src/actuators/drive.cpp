#include "drive.h"

#include <Arduino.h>
#include <ESP32Encoder.h>
#include <math.h>

#include "../config.h"
#include "../pins.h"

namespace {

// LEDC channels 0-3 run on timers 0 and 1; the servos use other timers.
constexpr uint8_t CH_LEFT_FWD = 0, CH_LEFT_REV = 1, CH_RIGHT_FWD = 2, CH_RIGHT_REV = 3;
constexpr uint32_t MAX_DUTY = (1u << config::DRIVE_PWM_BITS) - 1;
constexpr uint32_t ODOMETRY_MS = 100;

ESP32Encoder leftEncoder, rightEncoder;
float targetLeft = 0, targetRight = 0;
float left = 0, right = 0;
bool enabled = false;
drive::Odometry odo{};
int64_t lastLeft = 0, lastRight = 0;
uint32_t lastOdometry = 0;

float approach(float value, float target, float step) {
  if (fabsf(target - value) <= step) return target;
  return value + (target > value ? step : -step);
}

void write(uint8_t fwd, uint8_t rev, float duty) {
  const uint32_t level = static_cast<uint32_t>(fabsf(duty) * MAX_DUTY);
  // Never drive both sides of an H-bridge at once.
  ledcWrite(duty > 0 ? rev : fwd, 0);
  ledcWrite(duty > 0 ? fwd : rev, duty == 0 ? 0 : level);
}

void setEnabled(bool on) {
  enabled = on;
  digitalWrite(pins::DRIVE_EN, on ? HIGH : LOW);
}

void updateOdometry() {
  const uint32_t now = millis();
  if (now - lastOdometry < ODOMETRY_MS) return;
  const float dt = (now - lastOdometry) / 1000.0f;
  lastOdometry = now;
  odo.countLeft = leftEncoder.getCount();
  odo.countRight = rightEncoder.getCount();
  const int64_t dl = odo.countLeft - lastLeft, dr = odo.countRight - lastRight;
  lastLeft = odo.countLeft;
  lastRight = odo.countRight;
  odo.calibrated = config::ENCODER_COUNTS_PER_REV > 0;
  if (!odo.calibrated) return;
  const float revL = dl / config::ENCODER_COUNTS_PER_REV, revR = dr / config::ENCODER_COUNTS_PER_REV;
  odo.rpmLeft = revL / dt * 60.0f;
  odo.rpmRight = revR / dt * 60.0f;
  odo.distanceM += fabsf(revL + revR) / 2.0f * PI * config::WHEEL_DIAMETER_M;
}

}  // namespace

namespace drive {

void begin() {
  pinMode(pins::DRIVE_EN, OUTPUT);
  setEnabled(false);
  const int outputs[4] = {pins::LEFT_RPWM, pins::LEFT_LPWM, pins::RIGHT_RPWM, pins::RIGHT_LPWM};
  for (uint8_t ch = 0; ch < 4; ch++) {
    ledcSetup(ch, config::DRIVE_PWM_HZ, config::DRIVE_PWM_BITS);
    ledcAttachPin(outputs[ch], ch);
    ledcWrite(ch, 0);
  }
  ESP32Encoder::useInternalWeakPullResistors = puType::none;  // input-only pins have none
  leftEncoder.attachFullQuad(pins::LEFT_ENC_A, pins::LEFT_ENC_B);
  rightEncoder.attachFullQuad(pins::RIGHT_ENC_A, pins::RIGHT_ENC_B);
  leftEncoder.clearCount();
  rightEncoder.clearCount();
  lastOdometry = millis();
}

void setTarget(float l, float r) {
  targetLeft = constrain(l, -1.0f, 1.0f);
  targetRight = constrain(r, -1.0f, 1.0f);
}

void stop() {
  targetLeft = targetRight = left = right = 0;
  write(CH_LEFT_FWD, CH_LEFT_REV, 0);
  write(CH_RIGHT_FWD, CH_RIGHT_REV, 0);
  setEnabled(false);
}

void update(float dt) {
  const float step = config::DRIVE_RAMP_PER_S * dt;
  // Reversing passes through zero first, so the gearbox never sees an instant flip.
  const float stepL = (targetLeft * left < 0) ? approach(left, 0, step * 2) : approach(left, targetLeft, step);
  const float stepR = (targetRight * right < 0) ? approach(right, 0, step * 2) : approach(right, targetRight, step);
  left = stepL;
  right = stepR;
  const bool moving = left != 0 || right != 0 || targetLeft != 0 || targetRight != 0;
  if (moving != enabled) setEnabled(moving);
  write(CH_LEFT_FWD, CH_LEFT_REV, left);
  write(CH_RIGHT_FWD, CH_RIGHT_REV, right);
  updateOdometry();
}

const Odometry &odometry() { return odo; }
float appliedLeft() { return left; }
float appliedRight() { return right; }

}  // namespace drive
