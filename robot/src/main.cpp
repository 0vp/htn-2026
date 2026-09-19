#include <Arduino.h>

#include "actuators/arm.h"
#include "actuators/drive.h"
#include "actuators/winches.h"
#include "config.h"
#include "net/authority.h"
#include "net/server.h"
#include "net/telemetry.h"

namespace {

constexpr uint32_t CONTROL_MS = 10;  // 100 Hz actuator loop
constexpr uint32_t LOG_MS = 500;
// Above the Arduino loop task (priority 1), so a network write blocked on a dead client
// can never delay the failsafe.
constexpr UBaseType_t CONTROL_PRIORITY = 5;

uint32_t lastTelemetry = 0, lastLog = 0;
uint32_t loops = 0;
float loopHz = 0;
volatile bool isLive = false;

/** Actuator task: the only code that drives motors, servos and winches. */
void controlTask(void *) {
  TickType_t wake = xTaskGetTickCount();
  uint32_t last = millis();
  bool wasLive = false;
  Command c;
  for (;;) {
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(CONTROL_MS));
    const uint32_t now = millis();
    const float dt = (now - last) / 1000.0f;
    last = now;

    const bool live = server::snapshot(c);
    if (live) {
      drive::setTarget(c.driveLeft, c.driveRight);
      if (c.hasArm) arm::setTarget(c.arm);
      winches::set(c.winch);
    } else if (wasLive) {
      // E-STOP, disarm or no fresh packet: stop at once. The worm gears self-lock and the
      // servos hold their last angle.
      drive::stop();
      winches::stop();
      Serial.printf("%lu stopped by control task (%s)\n", static_cast<unsigned long>(now),
                    server::estopLatched() ? "e-stop" : "no fresh command");
    }
    wasLive = live;
    isLive = live;
    drive::update(dt);
    arm::update(dt);
    winches::update(dt);
  }
}

void log() {
  const drive::Odometry &odo = drive::odometry();
  const authority::Status control = authority::status();
  Serial.printf("clients %u  %s  owner %s%s  duty L %+.2f R %+.2f  pack %.2fV  enc L %lld R %lld  loop %.0f Hz\n",
                server::clientCount(), isLive ? "LIVE" : (control.latched ? "E-STOP" : "idle"),
                authority::roleName(control.owner), control.supervised ? " (auto)" : "", drive::appliedLeft(),
                drive::appliedRight(), telemetry::packVolts(), odo.countLeft, odo.countRight, loopHz);
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
  xTaskCreatePinnedToCore(controlTask, "control", 4096, nullptr, CONTROL_PRIORITY, nullptr, 1);
  lastTelemetry = lastLog = millis();
}

/** Network, telemetry and logging. May stall on a dead client; the control task doesn't care. */
void loop() {
  server::loop();
  telemetry::update();
  loops++;

  const uint32_t now = millis();
  if (now - lastTelemetry >= config::TELEMETRY_MS) {
    loopHz = loops * 1000.0f / (now - lastTelemetry);
    loops = 0;
    lastTelemetry = now;
    char json[768];
    const size_t n = telemetry::build(json, sizeof json, loopHz);
    if (n) server::broadcast(json, n);
  }
  if (now - lastLog >= LOG_MS) {
    lastLog = now;
    log();
  }
}
