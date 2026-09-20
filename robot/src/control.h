// Hardware-free command state: supervision, watchdog, E-STOP latch, ramp and reversal pause.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

constexpr float MAX_DUTY = .6f;
constexpr float RAMP_PER_S = 1.5f;
constexpr uint32_t WATCHDOG_MS = 300;
constexpr uint32_t REVERSE_PAUSE_MS = 250;

struct Wheel {
  float target = 0, duty = 0;
  uint32_t zeroSince = 0;

  // Ramps toward the target; a sign change first rests at zero for REVERSE_PAUSE_MS.
  void tick(uint32_t now, float seconds) {
    const float step = RAMP_PER_S * std::min(std::max(seconds, 0.f), .05f);
    const bool reversing = duty != 0 && target * duty < 0;
    const float goal = reversing ? 0 : target;
    if (duty == 0 && target != 0 && now - zeroSince < REVERSE_PAUSE_MS) return;
    const float before = duty;
    duty += std::min(std::max(goal - duty, -step), step);
    if (before != 0 && duty == 0) zeroSince = now;
  }
  void halt(uint32_t now) {
    if (duty != 0) zeroSince = now;
    target = duty = 0;
  }
};

struct Control {
  Wheel left, right;
  bool supervised = false, estop = false, timedOut = false;
  uint32_t lastCommand = 0;

  bool armed() const { return left.target != 0 || right.target != 0; }
  void stop(uint32_t now) { left.halt(now), right.halt(now); }

  void supervise(bool enabled, uint32_t now) {
    supervised = enabled;
    if (!enabled) stop(now);
  }
  // Returns false when the command was rejected (and the base stopped).
  bool command(bool arm, bool stopLatch, float l, float r, uint32_t now) {
    if (stopLatch) estop = true;
    const bool valid = std::isfinite(l) && std::isfinite(r) && std::abs(l) <= MAX_DUTY &&
                       std::abs(r) <= MAX_DUTY;
    if (!arm || estop || !supervised || !valid) {
      stop(now);
      return !arm && !stopLatch ? true : false;
    }
    left.target = l, right.target = r;
    lastCommand = now, timedOut = false;
    return true;
  }
  void tick(uint32_t now, float seconds) {
    if (armed() && now - lastCommand > WATCHDOG_MS) stop(now), timedOut = true;
    left.tick(now, seconds), right.tick(now, seconds);
  }
};
