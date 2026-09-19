#pragma once

#include <stdint.h>

#include "../hal/display.h"

/**
 * The dashboard's look (fe/src/styles.css) on a 320x240 LCD: warm paper with a dot grid, ink
 * type, deep-blue blocks with a stepped band into the paper, signal red, square corners,
 * hairlines and tracked uppercase labels. The frame is a palette sprite, so these are exact
 * colours rather than RGB332 approximations; draw with the `C` indices below.
 */
namespace theme {

enum C : uint8_t {
  PAPER,
  PAPER_2,
  INK,
  INK_60,
  INK_35,
  HAIRLINE,
  DOT,
  BLUE,
  BLUE_DEEP,
  BLUE_SOFT,
  SIGNAL,
  OK,
  WARN,
  WHITE,
  // Four stepped bands from each block colour to paper, plus a muted text tone on the block.
  BLUE_BAND,
  OK_BAND = BLUE_BAND + 5,
  SIGNAL_BAND = OK_BAND + 5,
  COUNT = SIGNAL_BAND + 5,
};

enum class Block : uint8_t { Blue, Ok, Signal };

/** Loads the palette into the frame sprite. Call once after display::begin(). */
void begin();

/** RGB888 of a palette entry, for screenshots. */
uint32_t rgb(uint8_t index);

uint8_t blockColour(Block b);
/** Step 0..3 of the band under a block (dark to light); step 4 is muted text on the block. */
uint8_t band(Block b, int step);

void dots(LGFX_Sprite &g, int x, int y, int w, int h);
void bands(LGFX_Sprite &g, Block b, int y);
void panel(LGFX_Sprite &g, int x, int y, int w, int h);

/** Tracked uppercase mono label (5x7 glyphs, 7 px advance). Datum is top-left/right/centre. */
enum class Align : uint8_t { Left, Right, Centre };
void label(LGFX_Sprite &g, const char *text, int x, int y, uint8_t colour, Align align = Align::Left);
int labelWidth(const char *text);

/** Chunky pixel type for headlines and readouts (8x8 glyphs times `scale`). */
void pixel(LGFX_Sprite &g, const char *text, int x, int y, int scale, uint8_t colour, Align align = Align::Left);
int pixelWidth(const char *text, int scale);

}  // namespace theme
