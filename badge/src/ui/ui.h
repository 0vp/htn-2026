#pragma once

#include "../control/control.h"

/** Everything the screen shows for one frame. */
struct UiModel {
  const Controller *controller;
  const ButtonState *input;
  const char *linkText;
  /** An agent client is connected and sending commands. */
  bool agentConnected;
  bool configured;
  int wifiRssi;
  uint32_t agentSilenceMs;
};

namespace ui {

/** Loads the colour palette. Call once after display::begin(). */
void begin();

/** Draws the boot splash. */
void splash(const char *message);

/** Renders a full frame into the sprite and pushes it. */
void render(const UiModel &model);

/** Streams the last frame over serial as hex (palette, then rows) for `shot`. */
void dumpFrame();

}  // namespace ui
