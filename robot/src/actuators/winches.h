#pragma once

#include <stdint.h>

/** Three N20 tendon winches on TB6612FNG drivers, each with end stops. */
namespace winches {

void begin();

/** Per winch: -1 reel in, 0 hold, 1 pay out. A direction into a pressed end stop is refused. */
void set(const int8_t command[3]);

/** Stops every winch and puts both TB6612s in standby. */
void stop();

void update(float dt);

/** Estimated spool position, 0 fully in .. 1 fully out (time-integrated, reset at end stops). */
float position(int winch);

/** Which end stop is pressed, inferred from the last direction of travel. */
bool atInEnd(int winch);
bool atOutEnd(int winch);

}  // namespace winches
