#pragma once

#include <stddef.h>
#include <stdint.h>

#include "../hal/buttons.h"

/**
 * Operator intent, the same shape as the dashboard's ControlState (fe/src/control/store.ts)
 * so the robot firmware parses one command format:
 *   drive.left/right  -1..1   signed duty for each BTS7960 (base motors)
 *   arm.*             degrees from each servo's mechanical neutral
 *   winch[i]          -1 reel in, 0 hold, 1 pay out (N20 via TB6612FNG)
 *   armed             false until the operator arms; nothing moves while false
 */
enum class Mode : uint8_t { Drive, Arm, Winch, Auto, Count };

enum Joint : uint8_t { Shoulder, Elbow, Wrist, JointCount };

constexpr uint8_t WINCH_COUNT = 3;

struct ControlState {
  bool estop = false;
  bool armed = false;
  float stickX = 0;  // > 0 turns clockwise seen from above
  float stickY = 0;  // > 0 drives forward
  float speedLimit = 0.5f;
  float arm[JointCount] = {0, 0, 0};
  int8_t winch[WINCH_COUNT] = {0, 0, 0};
};

struct WheelDuty {
  float left;
  float right;
};

const char *modeName(Mode mode);
const char *jointName(Joint joint);
void jointLimits(Joint joint, int &lo, int &hi);

class Controller {
 public:
  /**
   * Maps one poll of the buttons onto the control state.
   *   B            E-STOP (latches, disarms)
   *   START hold   arm (only while the link is up); tap START again to disarm
   *   HOME         next mode
   *   Drive        D-pad drives while held, A cycles the speed limit
   *   Arm          Left/Right picks a joint, Up/Down moves it, A re-centres it
   *   Winch        Left/Right picks a winch, Up reels in, Down pays out, A stops all
   *   Auto         armed, the badge only supervises and the agent drives; any button is an E-STOP
   */
  void update(const ButtonState &input, float dt, bool linkUp);

  /** Clears all motion and disarms, e.g. when the link drops. */
  void disarm();

  bool canMove() const { return state_.armed && !state_.estop; }
  /** Armed in AUTO: packets are a supervision heartbeat for the agent, not drive commands. */
  bool supervising() const { return mode_ == Mode::Auto && canMove(); }
  WheelDuty mix() const;

  /** Writes the JSON command packet; returns its length (0 if `size` was too small). */
  size_t packet(char *out, size_t size, uint32_t seq, uint64_t timeMs) const;

  /** Switches the screen's mode (console `mode`); motion commands in the old mode are released. */
  void setMode(Mode mode) { mode_ = mode; }

  const ControlState &state() const { return state_; }
  Mode mode() const { return mode_; }
  uint8_t selectedJoint() const { return joint_; }
  uint8_t selectedWinch() const { return winch_; }
  /** 0..1 progress of the START hold towards arming. */
  float armProgress() const { return armHold_ / ARM_HOLD_S; }

 private:
  static constexpr float ARM_HOLD_S = 1.0f;

  void driveInput(const ButtonState &input, float dt);
  void armInput(const ButtonState &input, float dt);
  void winchInput(const ButtonState &input);

  ControlState state_;
  Mode mode_ = Mode::Drive;
  uint8_t joint_ = Shoulder;
  uint8_t winch_ = 0;
  float armHold_ = 0;
  bool startConsumed_ = false;
};
