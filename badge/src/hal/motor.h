#pragma once

/**
 * Drive motor (BTS7960) and MG90S steering servo, with the same limits and slew rates as
 * robot/steering: 30% duty, 20 degrees of servo offset, 0.5 duty/s and 30 deg/s, and outputs
 * that start at zero. RPWM and LPWM are never energised together.
 */
namespace motor {

void begin();

/** Ramps towards `duty` (-0.3..0.3) and `steering` degrees and writes the outputs. */
void apply(float duty, float steering, float dt);

/** Cuts drive at once; the servo holds its last commanded angle. */
void stop();

float appliedDuty();
float appliedSteering();

}  // namespace motor
