#pragma once

#include <stdint.h>

/**
 * Badge wiring, read from the stock firmware's GPIO matrix over JTAG (see README).
 * The C3 exposes few pins: everything below is fixed by the PCB.
 */
namespace board {

// ST7789 2.0" 320x240 LCD on SPI2 (from the stock esp_lcd config). The backlight is always on.
constexpr int LCD_SCLK = 1;
constexpr int LCD_MOSI = 10;
constexpr int LCD_CS = 2;
constexpr int LCD_DC = 0;
constexpr int LCD_RST = 4;

// 74HC165 shift register for the face buttons, bit-banged.
constexpr int SR_LOAD = 20;
constexpr int SR_CLK = 21;
constexpr int SR_DATA_DEFAULT = 7;

// START is the BOOT strap and has its own pin (active low).
constexpr int BTN_START = 9;

// The badge drives nothing itself, so GPIO 3 (WS2812B ring), 5 and 6 (I2C) stay unused.

constexpr int SCREEN_W = 320;
constexpr int SCREEN_H = 240;

}  // namespace board
