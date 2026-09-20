#pragma once

#include <stdint.h>

#include "../hal/buttons.h"

/**
 * Operator intent for the fixed drive wheel and steering servo. The badge is the robot
 * controller now, so DRIVE moves the robot from the D-pad and AUTO hands driving to the agent
 * while the human supervises. Limits match robot/steering: 30% duty, 20 degrees of offset.
 */
enum class Mode : uint8_t { Drive, Auto, Count };

constexpr float MAX_DUTY = 0.3f;
constexpr float MAX_STEERING_DEG = 20.0f;

struct ControlState {
  bool estop = false;
  bool armed = false;
  float stickX = 0;  // > 0 steers one way; a servo offset, never a measured yaw
  float stickY = 0;  // > 0 drives forward
  float speedLimit = 0.5f;
};

const char *modeName(Mode mode);

class Controller {
 public:
  /**
   * Maps one poll of the buttons onto the control state.
   *   B            E-STOP (latches until a human arms again)
   *   START hold   arm; tap START again to disarm
   *   HOME         next mode
   *   Drive        D-pad drives the robot while held, A cycles the speed limit
   *   Auto         armed, the badge supervises and the agent drives; any button is an E-STOP
   */
  void update(const ButtonState &input, float dt);

  /** Clears motion and disarms. */
  void disarm();

  bool canMove() const { return state_.armed && !state_.estop; }
  /** Armed in AUTO: the agent may drive while this stays true. */
  bool supervising() const { return mode_ == Mode::Auto && canMove(); }
  /** True while the human is driving from the badge's own D-pad. */
  bool driving() const { return mode_ == Mode::Drive && canMove(); }

  /** Commanded duty (-0.3..0.3) and steering offset (-20..20 degrees) from the D-pad. */
  float duty() const;
  float steering() const;

  /** Switches the screen's mode (console `mode`); motion in the old mode is released. */
  void setMode(Mode mode) { mode_ = mode; }

  const ControlState &state() const { return state_; }
  Mode mode() const { return mode_; }
  /** 0..1 progress of the START hold towards arming. */
  float armProgress() const { return armHold_ / ARM_HOLD_S; }

 private:
  static constexpr float ARM_HOLD_S = 1.0f;

  void driveInput(const ButtonState &input, float dt);

  ControlState state_;
  Mode mode_ = Mode::Drive;
  float armHold_ = 0;
  bool startConsumed_ = false;
};
