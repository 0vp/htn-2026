#pragma once

#include <stdint.h>

/** Two BTS7960-driven base motors with Walfront quadrature encoders. */
namespace drive {

void begin();

/** Target duty per wheel, -1..1 (positive drives forward). Ramped in `update()`. */
void setTarget(float left, float right);

/** Cuts both outputs immediately and drops the BTS7960 enables. */
void stop();

void update(float dt);

struct Odometry {
  bool calibrated;  // false until config::ENCODER_COUNTS_PER_REV is set
  float rpmLeft;
  float rpmRight;
  float distanceM;
  int64_t countLeft;
  int64_t countRight;
};

const Odometry &odometry();

/** Duty currently applied, for the amps estimate and logs. */
float appliedLeft();
float appliedRight();

}  // namespace drive
