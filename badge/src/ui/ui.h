#pragma once

#include "../control/control.h"
#include "../link/client.h"

/** Everything the screen shows for one frame. */
struct UiModel {
  const Controller *controller;
  const ButtonState *input;
  const char *linkText;
  /** The WebSocket to drive.py is up. */
  bool linked;
  bool configured;
  int wifiRssi;
  /** What drive.py last reported about the base; `valid` is false until a frame arrives. */
  robotlink::Telemetry robot;
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
