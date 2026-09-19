#pragma once

#include <stdint.h>

/** Ring of six WS2812B LEDs used as a status light visible from across the room. */
namespace leds {

void begin();

/** Sets every LED; `pulse` breathes the colour instead of holding it. */
void show(uint8_t r, uint8_t g, uint8_t b, bool pulse);

/** Call every loop to animate. */
void tick();

}  // namespace leds
