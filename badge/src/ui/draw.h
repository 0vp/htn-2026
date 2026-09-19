#pragma once

#include "../hal/display.h"
#include "ui.h"

/** Shared palette and drawing helpers for the UI files. */
namespace ui::draw {

constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

constexpr uint16_t BG = rgb(10, 12, 18);
constexpr uint16_t PANEL = rgb(28, 32, 44);
constexpr uint16_t LINE = rgb(60, 68, 88);
constexpr uint16_t TEXT = rgb(235, 238, 245);
constexpr uint16_t MUTED = rgb(140, 148, 168);
constexpr uint16_t ACCENT = rgb(64, 160, 255);
constexpr uint16_t GO = rgb(40, 200, 110);
constexpr uint16_t WARN = rgb(255, 176, 32);
constexpr uint16_t STOP = rgb(235, 50, 50);

/** Main content area between the banner and the footer. */
constexpr int TOP = 66;
constexpr int BOTTOM = 206;

/** Horizontal bar for a value in [lo, hi] with a centre mark at zero. */
void centredBar(LGFX_Sprite &g, int x, int y, int w, int h, float value, float lo, float hi, uint16_t colour);

/** Vertical bar for a signed value in [-1, 1], filling up or down from the middle. */
void signedColumn(LGFX_Sprite &g, int x, int y, int w, int h, float value, uint16_t colour);

void driveView(LGFX_Sprite &g, const UiModel &m);
void armView(LGFX_Sprite &g, const UiModel &m);
void winchView(LGFX_Sprite &g, const UiModel &m);
void setupView(LGFX_Sprite &g, const UiModel &m);

}  // namespace ui::draw
