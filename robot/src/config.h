#pragma once

#include <stdint.h>

/** Tunables. Values marked CALIBRATE are placeholders until measured on the built robot. */
namespace config {

// Network: the robot runs its own access point; the badge and dashboard join it.
constexpr const char *AP_SSID = "htn-robot";
constexpr uint8_t AP_CHANNEL = 6;
constexpr uint16_t CONTROL_PORT = 81;  // ws://192.168.4.1:81/

// Command safety.
constexpr uint32_t FAILSAFE_MS = 300;        // no packet from the operator -> stop moving
constexpr uint32_t RELEASE_OWNER_MS = 2000;  // silent operator loses control

// Drive.
constexpr uint32_t DRIVE_PWM_HZ = 20000;
constexpr uint8_t DRIVE_PWM_BITS = 10;
constexpr float DRIVE_RAMP_PER_S = 2.0f;  // duty change per second (setup note 5)
constexpr float WHEEL_DIAMETER_M = 0.095f;
// CALIBRATE: quadrature counts per wheel revolution. 0 leaves rpm/odometry out of telemetry;
// the serial log prints raw counts so you can turn a wheel 10 times and divide.
constexpr float ENCODER_COUNTS_PER_REV = 0;

// Servos: pulse = neutral + sign * degrees * usPerDegree, clamped to 500..2500 us.
// CALIBRATE: assumes 270-degree servos centred at 1500 us.
struct ServoCal {
  uint16_t neutralUs;
  float usPerDegree;
  int8_t sign;
  int16_t minDeg;
  int16_t maxDeg;
};
constexpr ServoCal SERVOS[3] = {
    {1500, 2000.0f / 270.0f, 1, -90, 90},    // shoulder (ANNIMOS 60kg)
    {1500, 2000.0f / 270.0f, 1, -120, 120},  // elbow (HOOYIJ RDS3225)
    {1500, 2000.0f / 270.0f, 1, -90, 90},    // wrist (HOOYIJ RDS3225)
};
constexpr float SERVO_DEG_PER_S = 60.0f;  // slew limit so joints never snap under load

// Winches. CALIBRATE: seconds for a full in -> out run, used to estimate spool position.
constexpr float WINCH_TRAVEL_S = 8.0f;
constexpr uint32_t LIMIT_DEBOUNCE_MS = 20;

// Battery: ADC millivolts x this = pack volts. CALIBRATE against a multimeter.
constexpr float BATTERY_SCALE = (100.0f + 27.0f) / 27.0f / 1000.0f;

constexpr uint32_t TELEMETRY_MS = 200;  // 5 Hz

}  // namespace config
