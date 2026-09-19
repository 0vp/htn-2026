#pragma once

#include "../control/control.h"

/** Everything the screen shows for one frame. */
struct UiModel {
  const Controller *controller;
  const ButtonState *input;
  const char *linkText;
  bool linkOpen;
  bool configured;
  int wifiRssi;
  uint32_t robotSilenceMs;
};

namespace ui {

/** Draws the boot splash straight to the panel. */
void splash(const char *message);

/** Renders a full frame into the sprite and pushes it. */
void render(const UiModel &model);

}  // namespace ui
