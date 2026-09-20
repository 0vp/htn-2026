#pragma once

#include <stdint.h>

#include "../hal/buttons.h"

/**
 * Operator intent for the differential base behind robot/scripts/drive.py. The badge is a pure
 * remote now: it owns no motors, and the D-pad produces the same logical command the laptop's
 * arrow keys do (drive.py -> KEYS and wheels()), so both drive the base through one code path.
 *
 * DRIVE mixes the D-pad into linear/angular; AUTO stays silent so the cloud agent drives while
 * the human here supervises. Values are logical -1..1 before drive.py applies calibration.json;
 * MAX_LEVEL matches drive.py's --limit so nothing is renormalised on the far side.
 */
enum class Mode : uint8_t { Drive, Auto, Count };

constexpr float MAX_LEVEL = 0.6f;

struct ControlState {
  bool estop = false;
  bool armed = false;
  float stickX = 0;  // > 0 turns right
  float stickY = 0;  // > 0 drives forward
  float speedLimit = 0.5f;
};

const char *modeName(Mode mode);

class Controller {
 public:
  /**
   * Maps one poll of the buttons onto the control state.
   *   B            stop and disarm, like drive.py's space bar
   *   B hold 1 s   latching E-STOP (the base firmware holds it until the board is reset)
   *   START hold   arm; tap START again to disarm
   *   HOME         next mode
   *   Drive        D-pad drives while held, A cycles the speed limit
   *   Auto         armed, the badge supervises and the agent drives; any button stops it
   */
  void update(const ButtonState &input, float dt);

  /** Clears motion and disarms. */
  void disarm();

  bool canMove() const { return state_.armed && !state_.estop; }
  /** Armed in AUTO: the agent may drive while this stays true. */
  bool supervising() const { return mode_ == Mode::Auto && canMove(); }
  /** True while the human is driving from the badge's own D-pad. */
  bool driving() const { return mode_ == Mode::Drive && canMove(); }

  /** Logical command for drive.py: + linear is forward, + angular turns left. */
  float linear() const;
  float angular() const;
  /** The wheel pair drive.py will derive, for the screen only. */
  float left() const { return linear() - angular(); }
  float right() const { return linear() + angular(); }

  /** Switches the screen's mode (console `mode`); motion in the old mode is released. */
  void setMode(Mode mode) { mode_ = mode; }

  const ControlState &state() const { return state_; }
  Mode mode() const { return mode_; }
  /** 0..1 progress of the START hold towards arming. */
  float armProgress() const { return armHold_ / ARM_HOLD_S; }
  /** 0..1 progress of the B hold towards a latching E-STOP. */
  float estopProgress() const { return stopHold_ / STOP_HOLD_S; }

 private:
  static constexpr float ARM_HOLD_S = 1.0f;
  static constexpr float STOP_HOLD_S = 1.0f;

  void driveInput(const ButtonState &input, float dt);

  ControlState state_;
  Mode mode_ = Mode::Drive;
  float armHold_ = 0;
  float stopHold_ = 0;
  bool startConsumed_ = false;
  bool stopConsumed_ = false;
};
