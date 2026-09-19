#pragma once
#include <cmath>
#include <cstdint>

// No movement on boot. Commands are bounded and expire locally without a host.
struct SteeringControl {
  bool supervised = false;
  bool active = false;
  bool estop = false;
  uint32_t heard = 0;
  float duty = 0;
  float steering = 0;  // Servo offset: subtract from 90 degrees; wheel direction uncalibrated.

  void stop() { active = false; duty = 0; }
  void supervise(bool enabled) {
    supervised = enabled;
    if (!enabled) stop();
  }
  bool command(bool armed, bool emergency, float speed, float angle, uint32_t now) {
    if (emergency) { estop = true; supervised = false; stop(); return false; }
    if (!armed) { stop(); return true; }
    if (!supervised || estop || !std::isfinite(speed) || !std::isfinite(angle)
        || std::abs(speed) > .3f || std::abs(angle) > 20) {
      stop(); return false;
    }
    duty = speed; steering = angle; heard = now; active = true;
    return true;
  }
  void tick(uint32_t now) {
    if (active && uint32_t(now - heard) > 300) stop();
  }
};
