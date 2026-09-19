#pragma once

#include "theme.h"
#include "ui.h"

/** Layout shared by the UI files. The frame is 320x240. */
namespace ui::draw {

constexpr int NAV_H = 28;       // wordmark + mode tabs
constexpr int BLOCK_Y = 28;     // state block
constexpr int BLOCK_H = 52;
constexpr int BANDS_Y = BLOCK_Y + BLOCK_H;
constexpr int TOP = BANDS_Y + 12 + 6;  // content starts under the bands
constexpr int FOOTER_Y = 212;
constexpr int BOTTOM = FOOTER_Y - 6;

void driveView(LGFX_Sprite &g, const UiModel &m);
void armView(LGFX_Sprite &g, const UiModel &m);
void winchView(LGFX_Sprite &g, const UiModel &m);
void setupView(LGFX_Sprite &g, const UiModel &m);

}  // namespace ui::draw
