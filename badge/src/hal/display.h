#pragma once

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

/** The badge's ST7789 panel, landscape 320x240. The backlight is always on. */
class BadgeLcd : public lgfx::LGFX_Device {
 public:
  explicit BadgeLcd(bool invert);

 private:
  lgfx::Panel_ST7789 panel_;
  lgfx::Bus_SPI bus_;
};

namespace display {

/** Brings up the panel and allocates the frame sprite. Returns false if memory ran out. */
bool begin(bool invert, bool flip);

/** Off-screen 8-bit frame. Draw into it, then call `present()`. */
LGFX_Sprite &frame();

void present();

}  // namespace display
