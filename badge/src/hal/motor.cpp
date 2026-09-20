#include "motor.h"

#include <Arduino.h>

#include "../board.h"

namespace {

// Channels 0/1 share the 10 kHz motor timer; channel 2 uses a separate 50 Hz servo timer.
constexpr uint8_t FORWARD = 0, REVERSE = 1, STEERING = 2;
constexpr float DUTY_PER_S = 0.5f;
constexpr float DEG_PER_S = 30.0f;

float duty = 0;
float steering = 0;

void writeMotor(float value) {
  // Zero the opposite input before changing direction. Never energize both.
  ledcWrite(value >= 0 ? REVERSE : FORWARD, 0);
  ledcWrite(value >= 0 ? FORWARD : REVERSE, static_cast<uint32_t>(fabsf(value) * 255));
}

void writeServo(float offset) {
  // Pulse convention only; physical wheel direction needs calibration.
  const float angle = 90 - offset;
  const float pulseUs = 600 + angle * 10;
  ledcWrite(STEERING, static_cast<uint32_t>(pulseUs / 20000 * 16383));
}

}  // namespace

namespace motor {

void begin() {
  pinMode(board::MOTOR_RPWM, OUTPUT);
  digitalWrite(board::MOTOR_RPWM, LOW);
  pinMode(board::MOTOR_LPWM, OUTPUT);
  digitalWrite(board::MOTOR_LPWM, LOW);
  ledcSetup(FORWARD, 10000, 8);
  ledcAttachPin(board::MOTOR_RPWM, FORWARD);
  ledcSetup(REVERSE, 10000, 8);
  ledcAttachPin(board::MOTOR_LPWM, REVERSE);
  ledcSetup(STEERING, 50, 14);
  ledcAttachPin(board::SERVO_SIGNAL, STEERING);
  writeMotor(0);
  writeServo(0);
}

void apply(float target, float angle, float dt) {
  const float step = dt < 0 ? 0 : (dt > 0.05f ? 0.05f : dt);
  duty += constrain(target - duty, -DUTY_PER_S * step, DUTY_PER_S * step);
  steering += constrain(angle - steering, -DEG_PER_S * step, DEG_PER_S * step);
  writeMotor(duty);
  writeServo(steering);
}

void stop() {
  duty = 0;
  writeMotor(0);
}

float appliedDuty() { return duty; }
float appliedSteering() { return steering; }

}  // namespace motor
