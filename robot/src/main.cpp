#include <Arduino.h>

#include "actuators/arm.h"
#include "actuators/drive.h"
#include "actuators/winches.h"
#include "net/server.h"

namespace {

constexpr uint32_t CONTROL_MS = 10;  // 100 Hz actuator loop
constexpr uint32_t LOG_MS = 2000;

uint32_t lastControl = 0, lastLog = 0;
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
  Serial.printf("clients %u  %s  enc L %lld R %lld\n", server::clientCount(),
                server::live() ? "LIVE" : (server::estopLatched() ? "E-STOP" : "idle"), odo.countLeft, odo.countRight);
}

}  // namespace

void setup() {
  Serial.begin(115200);
  // Outputs first, so every motor pin is driven low before anything else runs.
  drive::begin();
  winches::begin();
  arm::begin();
  server::begin();
  lastControl = lastLog = millis();
}

void loop() {
  server::loop();

  const uint32_t now = millis();
  if (now - lastControl >= CONTROL_MS) {
    control((now - lastControl) / 1000.0f);
    lastControl = now;
  }
  if (now - lastLog >= LOG_MS) {
    lastLog = now;
    log();
  }
}
