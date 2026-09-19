#pragma once

/** Shoulder, elbow and wrist hobby servos, slew-limited. */
namespace arm {

void begin();

/** Joint targets in degrees from neutral. The first call after boot attaches the servos. */
void setTarget(const float degrees[3]);

void update(float dt);

/** Last commanded angle per joint (hobby servos report no position back). */
float angle(int joint);

bool attached();

}  // namespace arm
