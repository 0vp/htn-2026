#include "telemetry.h"

#include <Arduino.h>
#include <stdio.h>

#include "../actuators/arm.h"
#include "../actuators/drive.h"
#include "../actuators/winches.h"
#include "../config.h"
#include "../pins.h"
#include "authority.h"

namespace {

float volts = NAN;
uint32_t lastSample = 0;

// Rough current from commanded duty; the build has no current sensor (matches the dashboard).
float ampsEstimate() {
  const float driveAmps = (fabsf(drive::appliedLeft()) + fabsf(drive::appliedRight())) * 2.5f;
  return 0.3f + driveAmps;
}

}  // namespace

namespace telemetry {

void begin() {
  analogSetPinAttenuation(pins::BATTERY_SENSE, ADC_11db);
  lastSample = millis();
}

void update() {
  if (millis() - lastSample < 50) return;
  lastSample = millis();
  const float sample = analogReadMilliVolts(pins::BATTERY_SENSE) * config::BATTERY_SCALE;
  volts = isnan(volts) ? sample : volts * 0.9f + sample * 0.1f;  // smooth motor ripple
}

float packVolts() { return volts; }

size_t build(char *out, size_t size, float loopHz) {
  const drive::Odometry &odo = drive::odometry();
  char rpm[96] = "";
  if (odo.calibrated) {
    snprintf(rpm, sizeof rpm, "\"rpm\":{\"left\":%.1f,\"right\":%.1f},\"odometerM\":%.2f,", odo.rpmLeft,
             odo.rpmRight, odo.distanceM);
  }
  const authority::Status control = authority::status();
  char extra[200];
  snprintf(extra, sizeof extra,
           "\"control\":{\"owner\":\"%s\",\"supervised\":%s,\"estop\":%s},"
           "\"duty\":{\"left\":%.2f,\"right\":%.2f},\"encoders\":{\"left\":%lld,\"right\":%lld},",
           authority::roleName(control.owner), control.supervised ? "true" : "false", control.latched ? "true" : "false",
           drive::appliedLeft(), drive::appliedRight(), odo.countLeft, odo.countRight);
  const int n = snprintf(
      out, size,
      "{\"type\":\"telemetry\",\"packVolts\":%.2f,\"ampsEstimate\":%.1f,%s%s"
      "\"servoDeg\":{\"shoulder\":%.0f,\"elbow\":%.0f,\"wrist\":%.0f},"
      "\"winchPos\":[%.2f,%.2f,%.2f],"
      "\"limits\":[[%s,%s],[%s,%s],[%s,%s]],"
      "\"loopHz\":%.0f,\"uptimeS\":%lu,\"heapKb\":%u}",
      isnan(volts) ? 0.0f : volts, ampsEstimate(), rpm, extra, arm::angle(0), arm::angle(1), arm::angle(2),
      winches::position(0), winches::position(1), winches::position(2), winches::atInEnd(0) ? "true" : "false",
      winches::atOutEnd(0) ? "true" : "false", winches::atInEnd(1) ? "true" : "false",
      winches::atOutEnd(1) ? "true" : "false", winches::atInEnd(2) ? "true" : "false",
      winches::atOutEnd(2) ? "true" : "false", loopHz, static_cast<unsigned long>(millis() / 1000),
      static_cast<unsigned>(ESP.getFreeHeap() / 1024));
  return n > 0 && static_cast<size_t>(n) < size ? n : 0;
}

}  // namespace telemetry
