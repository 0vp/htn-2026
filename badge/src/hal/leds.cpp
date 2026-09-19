#include "leds.h"

#include <Adafruit_NeoPixel.h>
#include <Arduino.h>

#include "../board.h"

namespace {

Adafruit_NeoPixel strip(board::LED_COUNT, board::LED_DATA, NEO_GRB + NEO_KHZ800);

constexpr uint8_t MAX_LEVEL = 40;  // The ring is bright and runs from AA cells.
constexpr uint32_t FRAME_MS = 40;

uint8_t red = 0, green = 0, blue = 0;
bool breathing = false;
uint32_t lastFrame = 0;

}  // namespace

namespace leds {

void begin() {
  strip.begin();
  strip.clear();
  strip.show();
}

void show(uint8_t r, uint8_t g, uint8_t b, bool pulse) {
  red = r;
  green = g;
  blue = b;
  breathing = pulse;
}

void tick() {
  const uint32_t now = millis();
  if (now - lastFrame < FRAME_MS) return;
  lastFrame = now;
  float level = MAX_LEVEL / 255.0f;
  if (breathing) level *= 0.25f + 0.75f * (0.5f + 0.5f * sinf(now / 300.0f));
  const uint32_t colour = strip.Color(red * level, green * level, blue * level);
  for (int i = 0; i < board::LED_COUNT; i++) strip.setPixelColor(i, colour);
  strip.show();
}

}  // namespace leds
