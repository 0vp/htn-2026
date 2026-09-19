#include <Arduino.h>

#include "actuators/arm.h"
#include "actuators/drive.h"
#include "actuators/winches.h"
#include "config.h"
#include "net/server.h"
#include "net/telemetry.h"

namespace {

constexpr uint32_t CONTROL_MS = 10;  // 100 Hz actuator loop
constexpr uint32_t LOG_MS = 500;

uint32_t lastControl = 0, lastTelemetry = 0, lastLog = 0;
uint32_t loops = 0;
float loopHz = 0;
bool wasLive = false;

void control(float dt) {
  if (server::live()) {
    const Command &c = server::command();
    drive::setTarget(c.driveLeft, c.driveRight);
    arm::setTarget(c.arm);
    winches::set(c.winch);
    wasLive = true;
  } else if (wasLive) {
    // E-STOP, disarm or lost packets: stop the motors at once. The worm gears self-lock and
    // the servos hold their last angle.
    drive::stop();
    winches::stop();
    wasLive = false;
    Serial.println(server::estopLatched() ? "stopped: e-stop" : "stopped: no fresh command");
  }
  drive::update(dt);
  arm::update(dt);
  winches::update(dt);
}

void log() {
  const drive::Odometry &odo = drive::odometry();
  Serial.printf("clients %u  %s  duty L %+.2f R %+.2f  pack %.2fV  enc L %lld R %lld  loop %.0f Hz\n",
                server::clientCount(), server::live() ? "LIVE" : (server::estopLatched() ? "E-STOP" : "idle"),
                drive::appliedLeft(), drive::appliedRight(), telemetry::packVolts(), odo.countLeft, odo.countRight, loopHz);
}

}  // namespace

void setup() {
  Serial.begin(115200);
  // Outputs first, so every motor pin is driven low before anything else runs.
  drive::begin();
  winches::begin();
  arm::begin();
  telemetry::begin();
  server::begin();
  lastControl = lastTelemetry = lastLog = millis();
}

void loop() {
  server::loop();
  telemetry::update();
  loops++;

  const uint32_t now = millis();
  if (now - lastControl >= CONTROL_MS) {
    control((now - lastControl) / 1000.0f);
    lastControl = now;
  }
  if (now - lastTelemetry >= config::TELEMETRY_MS) {
    loopHz = loops * 1000.0f / (now - lastTelemetry);
    loops = 0;
    lastTelemetry = now;
    char json[512];
    const size_t n = telemetry::build(json, sizeof json, loopHz);
    if (n) server::broadcast(json, n);
  }
  if (now - lastLog >= LOG_MS) {
    lastLog = now;
    log();
  }
}
