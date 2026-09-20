#pragma once

#include <math.h>
#include <stdint.h>

/**
 * Bounded drive state for the fixed wheel and steering servo, mirroring
 * robot/steering/src/control.h so the agent's motion skills see the same rules here:
 * nothing moves on boot, commands expire locally after 300 ms without the host, an
 * emergency stop latches, and supervision can only be granted on the badge itself.
 */
struct SteeringControl {
  bool supervised = false;
  bool active = false;
  bool estop = false;
  uint32_t heard = 0;
  float duty = 0;
  float steering = 0;  // Servo offset: subtract from 90 degrees; wheel direction uncalibrated.

  void stop() {
    active = false;
    duty = 0;
  }

  void supervise(bool enabled) {
    supervised = enabled;
    if (!enabled) stop();
  }

  /** Returns false when the command was refused; an emergency latches until a human clears it. */
  bool command(bool armed, bool emergency, float speed, float angle, uint32_t now) {
    if (emergency) {
      estop = true;
      supervised = false;
      stop();
      return false;
    }
    if (!armed) {
      stop();
      return true;
    }
    if (!supervised || estop || !isfinite(speed) || !isfinite(angle) || fabsf(speed) > 0.3f ||
        fabsf(angle) > 20) {
      stop();
      return false;
    }
    duty = speed;
    steering = angle;
    heard = now;
    active = true;
    return true;
  }

  void tick(uint32_t now) {
    if (active && static_cast<uint32_t>(now - heard) > 300) stop();
  }
};
