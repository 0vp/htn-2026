#include "control.h"

#include <math.h>

namespace {

const char *const MODE_NAMES[] = {"DRIVE", "AUTO"};
const float SPEED_STEPS[] = {0.25f, 0.5f, 0.75f, 1.0f};

// Gradual acceleration; the motor output ramps again at 0.5 duty/s before the wheel sees it.
constexpr float STICK_RISE_PER_S = 2.5f;
constexpr float STICK_FALL_PER_S = 6.0f;

float clampf(float v, float lo = -1, float hi = 1) { return v < lo ? lo : (v > hi ? hi : v); }

/** Moves `value` towards `target`, rising and falling at separate rates. */
float ramp(float value, float target, float dt) {
  const bool speeding = fabsf(target) > fabsf(value) && target * value >= 0;
  const float step = (speeding ? STICK_RISE_PER_S : STICK_FALL_PER_S) * dt;
  if (fabsf(target - value) <= step) return target;
  return value + (target > value ? step : -step);
}

float axis(const ButtonState &in, Button negative, Button positive) {
  return (in.isHeld(positive) ? 1.0f : 0.0f) - (in.isHeld(negative) ? 1.0f : 0.0f);
}

}  // namespace

const char *modeName(Mode mode) { return MODE_NAMES[static_cast<uint8_t>(mode)]; }

void Controller::disarm() {
  state_.armed = false;
  state_.stickX = state_.stickY = 0;
}

void Controller::update(const ButtonState &in, float dt) {
  // While the agent drives, any new button edge (START, HOME and the slide included) stops it.
  // Holding START from arming isn't an edge, so it doesn't trip this.
  if (supervising() && (in.pressed || in.released & (1u << static_cast<uint8_t>(Button::Aux1)))) {
    state_.estop = true;
    disarm();
    startConsumed_ = true;
    return;
  }
  if (in.wasPressed(Button::B)) {
    state_.estop = true;
    disarm();
  }

  // START: a tap disarms; a one-second hold arms and clears the E-STOP.
  if (in.wasPressed(Button::Start)) {
    startConsumed_ = false;
    if (state_.armed) {
      disarm();
      startConsumed_ = true;
    }
  }
  if (in.isHeld(Button::Start) && !startConsumed_) {
    armHold_ += dt;
    if (armHold_ >= ARM_HOLD_S) {
      state_.estop = false;
      state_.armed = true;
      startConsumed_ = true;
    }
  } else {
    armHold_ = 0;
  }

  if (in.wasPressed(Button::Home)) {
    mode_ = static_cast<Mode>((static_cast<uint8_t>(mode_) + 1) % static_cast<uint8_t>(Mode::Count));
  }
  if (mode_ != Mode::Drive) {
    state_.stickX = state_.stickY = 0;
  } else {
    driveInput(in, dt);
  }
}

void Controller::driveInput(const ButtonState &in, float dt) {
  if (in.wasPressed(Button::A)) {
    size_t next = 0;
    for (size_t i = 0; i < sizeof(SPEED_STEPS) / sizeof(float); i++) {
      if (SPEED_STEPS[i] <= state_.speedLimit + 0.01f) next = i + 1;
    }
    state_.speedLimit = SPEED_STEPS[next % (sizeof(SPEED_STEPS) / sizeof(float))];
  }
  const bool live = canMove();
  state_.stickX = ramp(state_.stickX, live ? axis(in, Button::Left, Button::Right) : 0, dt);
  state_.stickY = ramp(state_.stickY, live ? axis(in, Button::Down, Button::Up) : 0, dt);
}

float Controller::duty() const {
  if (!driving()) return 0;
  return clampf(state_.stickY) * state_.speedLimit * MAX_DUTY;
}

float Controller::steering() const {
  if (mode_ != Mode::Drive) return 0;
  return clampf(state_.stickX) * MAX_STEERING_DEG;
}
