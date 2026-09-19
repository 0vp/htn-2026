#pragma once
#include <cmath>
#include <cstdint>

// No movement on boot. Commands are bounded and expire locally without a host.
struct SteeringControl {
  bool supervised = false;
  bool active = false;
  bool estop = false;
  uint32_t heard = 0;
  uint32_t supervisionAt = 0;
  bool leasedSupervision = false;
  float duty = 0;
  float steering = 0;  // Servo offset: subtract from 90 degrees; wheel direction uncalibrated.

  void stop() { active = false; duty = 0; }
  void supervise(bool enabled) {
    supervised = enabled;
    leasedSupervision = false;
    if (!enabled) stop();
  }
  void superviseFor(uint32_t now) {
    supervised = !estop; leasedSupervision = true; supervisionAt = now;
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
    if (leasedSupervision && uint32_t(now - supervisionAt) > 2000) supervise(false);
    if (active && uint32_t(now - heard) > 300) {
      stop();
      if (leasedSupervision) supervise(false);
    }
  }
};
