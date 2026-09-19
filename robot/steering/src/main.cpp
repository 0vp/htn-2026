#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include "control.h"
#include "protocol.h"

namespace {
constexpr int RPWM = 14, LPWM = 47, SERVO = 13, ENC_A = 41, ENC_B = 42;
// Channels 0/1 share the 10kHz motor timer; channel 2 uses a separate 50Hz timer.
constexpr int FORWARD = 0, REVERSE = 1, STEERING = 2;
SteeringControl control;
char buffer[512];
size_t used = 0;
bool overflow = false;
uint32_t lastTelemetry = 0, lastStep = 0;
float appliedDuty = 0, appliedSteering = 0;
volatile int32_t ticks = 0;
volatile uint8_t previous = 0;
portMUX_TYPE encoderMux = portMUX_INITIALIZER_UNLOCKED;

void IRAM_ATTR encoder() {
  const uint8_t state = (digitalRead(ENC_A) << 1) | digitalRead(ENC_B);
  const int8_t changes[16] = {0,-1,1,0,1,0,0,-1,-1,0,0,1,0,1,-1,0};
  portENTER_CRITICAL_ISR(&encoderMux);
  ticks += changes[(previous << 2) | state];
  previous = state;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

void motor(float duty) {
  // Zero the opposite input before changing direction. Never energize both.
  ledcWrite(duty >= 0 ? REVERSE : FORWARD, 0);
  ledcWrite(duty >= 0 ? FORWARD : REVERSE, uint32_t(std::abs(duty) * 255));
}

void servo(float offset) {
  const float angle = 90 - offset;  // Pulse convention only; physical wheel direction needs calibration.
  const float pulseUs = 600 + angle * 10;
  ledcWrite(STEERING, uint32_t(pulseUs / 20000 * 16383));
}

void packet() { handlePacket(buffer, used, control, millis()); }

void telemetry(uint32_t now) {
  if (now - lastTelemetry < 50) return;
  lastTelemetry = now;
  JsonDocument doc;
  doc["type"] = "telemetry";
  doc["drivetrain"] = "single_steer_v1";
  doc["uptime_ms"] = now;
  doc["reset_reason"] = int(esp_reset_reason());
  doc["motor_duty"] = appliedDuty;
  doc["steering_deg"] = appliedSteering;
  doc["steering_feedback"] = "commanded_servo_pulse_not_measured_angle";
  doc["odometry_calibrated"] = false;
  portENTER_CRITICAL(&encoderMux);
  const int32_t count = ticks;
  portEXIT_CRITICAL(&encoderMux);
  doc["encoder_ticks"] = count;
  doc["control"]["supervised"] = control.supervised;
  doc["control"]["estop"] = control.estop;
  doc["control"]["owner"] = control.active ? "agent" : "none";
  doc["capabilities"]["drive_base"] = true;
  doc["capabilities"]["set_arm"] = false;
  doc["capabilities"]["run_winch"] = false;
  serializeJson(doc, Serial);
  Serial.println();
}
}  // namespace

void setup() {
  pinMode(RPWM, OUTPUT); digitalWrite(RPWM, LOW);
  pinMode(LPWM, OUTPUT); digitalWrite(LPWM, LOW);
  ledcSetup(FORWARD, 10000, 8); ledcAttachPin(RPWM, FORWARD);
  ledcSetup(REVERSE, 10000, 8); ledcAttachPin(LPWM, REVERSE);
  ledcSetup(STEERING, 50, 14); ledcAttachPin(SERVO, STEERING);
  motor(0); servo(0);
  pinMode(ENC_A, INPUT); pinMode(ENC_B, INPUT);
  previous = (digitalRead(ENC_A) << 1) | digitalRead(ENC_B);
  attachInterrupt(ENC_A, encoder, CHANGE);
  attachInterrupt(ENC_B, encoder, CHANGE);
  Serial.begin(115200);
  lastStep = millis();
}

void loop() {
  // Bounded input work ensures a flooded or partial line cannot starve expiry.
  for (int budget = 0; budget < 128 && Serial.available(); ++budget) {
    char c = Serial.read();
    if (c == '\n') {
      if (!overflow && used) packet();
      else if (overflow) control.stop();
      used = 0; overflow = false;
    } else if (!overflow) {
      if (used < sizeof(buffer)) buffer[used++] = c;
      else { overflow = true; control.stop(); }
    }
  }
  const uint32_t now = millis();
  control.tick(now);
  const float dt = min(uint32_t(now - lastStep), uint32_t(50)) / 1000.f;
  lastStep = now;
  // Immediate electrical stop; bounded acceleration and steering slew otherwise.
  if (!control.active) appliedDuty = 0;
  else {
    const float error = control.duty - appliedDuty;
    appliedDuty += constrain(error, -.5f * dt, .5f * dt);
  }
  appliedSteering += constrain(control.steering-appliedSteering, -30.f*dt, 30.f*dt);
  motor(appliedDuty); servo(appliedSteering);
  telemetry(now);
  delay(1);
}
