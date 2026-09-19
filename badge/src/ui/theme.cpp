#include "theme.h"

#include <ctype.h>
#include <string.h>

namespace theme {

namespace {

constexpr uint32_t BASE[] = {
    0xf4f3ee,  // PAPER
    0xfbfaf6,  // PAPER_2
    0x171818,  // INK
    0x6b6b69,  // INK_60: ink at 60% on paper
    0xa3a29e,  // INK_35
    0xd0cfcb,  // HAIRLINE: ink at 16%
    0xd6d5d1,  // DOT: ink at 13%
    0x1520b8,  // BLUE
    0x0f188f,  // BLUE_DEEP
    0xccdbff,  // BLUE_SOFT
    0xeb1700,  // SIGNAL
    0x1f8a4c,  // OK
    0xc98a00,  // WARN
    0xffffff,  // WHITE
};

constexpr uint32_t PAPER_RGB = 0xf4f3ee;
constexpr int DOT_PITCH = 12;
constexpr int BAND_ROW = 3;
constexpr int LABEL_ADVANCE = 7;

uint32_t mix(uint32_t a, uint32_t b, float t) {
  auto ch = [&](int shift) {
    const float x = ((a >> shift) & 0xFF) * (1 - t) + ((b >> shift) & 0xFF) * t;
    return static_cast<uint32_t>(x + 0.5f) << shift;
  };
  return ch(16) | ch(8) | ch(0);
}

uint8_t firstBand(Block b) {
  return b == Block::Ok ? OK_BAND : (b == Block::Signal ? SIGNAL_BAND : BLUE_BAND);
}

}  // namespace

void begin() {
  uint32_t palette[COUNT];
  memcpy(palette, BASE, sizeof BASE);
  const uint32_t blocks[3] = {BASE[BLUE], BASE[OK], BASE[SIGNAL]};
  const uint8_t starts[3] = {BLUE_BAND, OK_BAND, SIGNAL_BAND};
  // Same steps as the dashboard's .bands (#4a53c9, #7b82d8, #aeb2e6, #d8d9ef for blue).
  const float steps[4] = {0.26f, 0.5f, 0.74f, 0.9f};
  for (int b = 0; b < 3; b++) {
    for (int i = 0; i < 4; i++) palette[starts[b] + i] = mix(blocks[b], PAPER_RGB, steps[i]);
    palette[starts[b] + 4] = mix(blocks[b], 0xffffff, 0.62f);
  }
  display::frame().createPalette(palette, COUNT);
}

uint8_t blockColour(Block b) { return b == Block::Ok ? OK : (b == Block::Signal ? SIGNAL : BLUE); }
uint8_t band(Block b, int step) { return firstBand(b) + step; }

void dots(LGFX_Sprite &g, int x, int y, int w, int h) {
  const int x0 = x + (DOT_PITCH - x % DOT_PITCH) % DOT_PITCH + 6;
  const int y0 = y + (DOT_PITCH - y % DOT_PITCH) % DOT_PITCH + 6;
  for (int py = y0; py < y + h; py += DOT_PITCH) {
    for (int px = x0; px < x + w; px += DOT_PITCH) g.drawPixel(px, py, DOT);
  }
}

void bands(LGFX_Sprite &g, Block b, int y) {
  for (int i = 0; i < 4; i++) g.fillRect(0, y + i * BAND_ROW, g.width(), BAND_ROW, band(b, i));
}

void panel(LGFX_Sprite &g, int x, int y, int w, int h) {
  g.fillRect(x, y, w, h, PAPER_2);
  g.drawRect(x, y, w, h, HAIRLINE);
}

int labelWidth(const char *text) {
  const int n = strlen(text);
  return n ? n * LABEL_ADVANCE - 2 : 0;
}

void label(LGFX_Sprite &g, const char *text, int x, int y, uint8_t colour, Align align) {
  const int w = labelWidth(text);
  if (align == Align::Right) x -= w;
  if (align == Align::Centre) x -= w / 2;
  g.setFont(&fonts::Font0);
  g.setTextSize(1);
  g.setTextColor(colour);
  g.setTextDatum(top_left);
  for (const char *p = text; *p; p++, x += LABEL_ADVANCE) g.drawChar(toupper(*p), x, y);
}

int pixelWidth(const char *text, int scale) { return strlen(text) * 8 * scale; }

void pixel(LGFX_Sprite &g, const char *text, int x, int y, int scale, uint8_t colour, Align align) {
  const int w = pixelWidth(text, scale);
  if (align == Align::Right) x -= w;
  if (align == Align::Centre) x -= w / 2;
  g.setFont(&fonts::Font8x8C64);
  g.setTextSize(scale);
  g.setTextColor(colour);
  g.setTextDatum(top_left);
  g.drawString(text, x, y);
  g.setTextSize(1);
}

}  // namespace theme
