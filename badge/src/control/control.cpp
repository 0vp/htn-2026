#include "control.h"

#include <math.h>
#include <stdio.h>

namespace {

const char *const MODE_NAMES[] = {"DRIVE", "ARM", "WINCH", "AUTO"};
const char *const JOINT_NAMES[] = {"shoulder", "elbow", "wrist"};
const int JOINT_LIMITS[JointCount][2] = {{-90, 90}, {-120, 120}, {-90, 90}};
const float SPEED_STEPS[] = {0.25f, 0.5f, 0.75f, 1.0f};

// Gradual motor acceleration (robot-shopping-list setup note 5); stopping is faster.
constexpr float STICK_RISE_PER_S = 2.5f;
constexpr float STICK_FALL_PER_S = 6.0f;
constexpr float JOINT_DEG_PER_S = 45.0f;

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
const char *jointName(Joint joint) { return JOINT_NAMES[joint]; }

void jointLimits(Joint joint, int &lo, int &hi) {
  lo = JOINT_LIMITS[joint][0];
  hi = JOINT_LIMITS[joint][1];
}

void Controller::disarm() {
  state_.armed = false;
  state_.stickX = state_.stickY = 0;
  for (auto &w : state_.winch) w = 0;
}

void Controller::update(const ButtonState &in, float dt, bool linkUp) {
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

  // START: a tap disarms; a one-second hold with the link up arms and clears the E-STOP.
  if (in.wasPressed(Button::Start)) {
    startConsumed_ = false;
    if (state_.armed) {
      disarm();
      startConsumed_ = true;
    }
  }
  if (in.isHeld(Button::Start) && !startConsumed_ && linkUp) {
    armHold_ += dt;
    if (armHold_ >= ARM_HOLD_S) {
      state_.estop = false;
      state_.armed = true;
      startConsumed_ = true;
    }
  } else {
    armHold_ = 0;
  }
  if (!linkUp && state_.armed) disarm();

  if (in.wasPressed(Button::Home)) {
    mode_ = static_cast<Mode>((static_cast<uint8_t>(mode_) + 1) % static_cast<uint8_t>(Mode::Count));
  }

  // Leaving a mode releases whatever it was driving.
  if (mode_ != Mode::Drive) state_.stickX = state_.stickY = 0;
  if (mode_ != Mode::Winch) {
    for (auto &w : state_.winch) w = 0;
  }

  switch (mode_) {
    case Mode::Drive:
      driveInput(in, dt);
      break;
    case Mode::Arm:
      armInput(in, dt);
      break;
    case Mode::Winch:
      winchInput(in);
      break;
    default:
      break;
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

void Controller::armInput(const ButtonState &in, float dt) {
  if (in.wasPressed(Button::Left)) joint_ = (joint_ + JointCount - 1) % JointCount;
  if (in.wasPressed(Button::Right)) joint_ = (joint_ + 1) % JointCount;
  int lo, hi;
  jointLimits(static_cast<Joint>(joint_), lo, hi);
  float &angle = state_.arm[joint_];
  if (in.wasPressed(Button::A)) angle = 0;
  // Servos hold their last command, so the arm is only adjusted while armed.
  if (canMove()) angle = clampf(angle + axis(in, Button::Down, Button::Up) * JOINT_DEG_PER_S * dt, lo, hi);
}

void Controller::winchInput(const ButtonState &in) {
  if (in.wasPressed(Button::Left)) winch_ = (winch_ + WINCH_COUNT - 1) % WINCH_COUNT;
  if (in.wasPressed(Button::Right)) winch_ = (winch_ + 1) % WINCH_COUNT;
  for (uint8_t i = 0; i < WINCH_COUNT; i++) state_.winch[i] = 0;
  if (!canMove() || in.isHeld(Button::A)) return;
  if (in.isHeld(Button::Up)) state_.winch[winch_] = -1;
  if (in.isHeld(Button::Down)) state_.winch[winch_] = 1;
}

WheelDuty Controller::mix() const {
  if (!canMove()) return {0, 0};
  const float x = state_.stickX, y = state_.stickY;
  return {clampf(y + x) * state_.speedLimit, clampf(y - x) * state_.speedLimit};
}

size_t Controller::packet(char *out, size_t size, uint32_t seq, uint64_t timeMs) const {
  const WheelDuty drive = mix();
  const bool live = canMove();
  const int n = snprintf(
      out, size,
      "{\"type\":\"command\",\"seq\":%lu,\"t\":%llu,\"estop\":%s,\"armed\":%s,"
      "\"drive\":{\"left\":%.3f,\"right\":%.3f},"
      "\"arm\":{\"shoulder\":%d,\"elbow\":%d,\"wrist\":%d},"
      "\"winch\":[%d,%d,%d],\"goal\":null,\"source\":\"badge\",\"auto\":%s}",
      static_cast<unsigned long>(seq), static_cast<unsigned long long>(timeMs), state_.estop ? "true" : "false",
      state_.armed ? "true" : "false", drive.left, drive.right, static_cast<int>(lroundf(state_.arm[Shoulder])),
      static_cast<int>(lroundf(state_.arm[Elbow])), static_cast<int>(lroundf(state_.arm[Wrist])),
      live ? state_.winch[0] : 0, live ? state_.winch[1] : 0, live ? state_.winch[2] : 0,
      mode_ == Mode::Auto ? "true" : "false");
  return n > 0 && static_cast<size_t>(n) < size ? n : 0;
}
