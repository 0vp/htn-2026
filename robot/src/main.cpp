// Stopped-by-default base firmware: newline JSON over UART0, two BTS7960 drivers, four IR inputs.
#include <Arduino.h>
#include <ArduinoJson.h>

#include "control.h"

constexpr int LEFT_REN = 4, LEFT_LEN = 5, LEFT_RPWM = 6, LEFT_LPWM = 7;
constexpr int RIGHT_REN = 15, RIGHT_LEN = 16, RIGHT_RPWM = 17, RIGHT_LPWM = 18;
constexpr int PWM_PINS[] = {LEFT_RPWM, LEFT_LPWM, RIGHT_RPWM, RIGHT_LPWM};
constexpr int ENABLE_PINS[] = {LEFT_REN, LEFT_LEN, RIGHT_REN, RIGHT_LEN};
// Physical order is not yet measured; keep neutral names.
constexpr int IR_PINS[] = {2, 42, 1, 41};
constexpr const char* DRIVETRAIN = "bts7960_diff_v2";

Control control;
String line;
uint32_t lastTick = 0, lastTelemetry = 0;

// channel: 0 = left, 1 = right. Only one of RPWM/LPWM is ever non-zero.
void drive(int channel, int renPin, int lenPin, float duty) {
  const uint32_t level = uint32_t(std::abs(duty) * 255);
  ledcWrite(channel * 2, duty > 0 ? level : 0);
  ledcWrite(channel * 2 + 1, duty < 0 ? level : 0);
  digitalWrite(renPin, level ? HIGH : LOW);
  digitalWrite(lenPin, level ? HIGH : LOW);
}

void apply() {
  drive(0, LEFT_REN, LEFT_LEN, control.left.duty);
  drive(1, RIGHT_REN, RIGHT_LEN, control.right.duty);
}

void handle(const String& text) {
  JsonDocument doc;
  const uint32_t now = millis();
  if (deserializeJson(doc, text)) return control.stop(now);
  const char* type = doc["type"] | "";
  if (!strcmp(type, "supervise")) return control.supervise(doc["enabled"] | false, now);
  if (strcmp(type, "command")) return control.stop(now);
  control.command(doc["armed"] | false, doc["estop"] | true, doc["motors"]["left"] | NAN,
                  doc["motors"]["right"] | NAN, now);
}

void telemetry() {
  JsonDocument doc;
  doc["type"] = "telemetry";
  doc["drivetrain"] = DRIVETRAIN;
  doc["uptime_ms"] = millis();
  doc["supervised"] = control.supervised;
  doc["armed"] = control.armed();
  doc["estop"] = control.estop;
  doc["watchdog_timed_out"] = control.timedOut;
  doc["max_duty"] = MAX_DUTY;
  doc["motors"]["left"] = control.left.duty;
  doc["motors"]["right"] = control.right.duty;
  JsonArray ir = doc["ir_raw"].to<JsonArray>();
  for (int pin : IR_PINS) ir.add(digitalRead(pin));
  serializeJson(doc, Serial);
  Serial.println();
}

void setup() {
  int channel = 0;
  for (int pin : ENABLE_PINS) pinMode(pin, OUTPUT), digitalWrite(pin, LOW);
  for (int pin : PWM_PINS) {
    ledcSetup(channel, 10000, 8);
    ledcAttachPin(pin, channel);
    ledcWrite(channel++, 0);
  }
  for (int pin : IR_PINS) pinMode(pin, INPUT);
  Serial.begin(115200);
}

void loop() {
  while (Serial.available()) {
    const char c = Serial.read();
    if (c == '\n') handle(line), line = "";
    else if (line.length() < 256) line += c;
    else line = "", control.stop(millis());
  }
  const uint32_t now = millis();
  if (now - lastTick >= 5) {
    control.tick(now, (now - lastTick) / 1000.f);
    lastTick = now;
    apply();
  }
  if (now - lastTelemetry >= 50) lastTelemetry = now, telemetry();
}
