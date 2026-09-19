#include "display.h"

#include "../board.h"

BadgeLcd::BadgeLcd(bool invert) {
  auto bus = bus_.config();
  bus.spi_host = SPI2_HOST;
  bus.spi_mode = 0;
  bus.freq_write = 40000000;
  bus.freq_read = 16000000;
  bus.spi_3wire = false;
  bus.use_lock = true;
  bus.dma_channel = SPI_DMA_CH_AUTO;
  bus.pin_sclk = board::LCD_SCLK;
  bus.pin_mosi = board::LCD_MOSI;
  bus.pin_miso = -1;
  bus.pin_dc = board::LCD_DC;
  bus_.config(bus);
  panel_.setBus(&bus_);

  auto panel = panel_.config();
  panel.pin_cs = board::LCD_CS;
  panel.pin_rst = board::LCD_RST;
  panel.pin_busy = -1;
  panel.panel_width = 240;
  panel.panel_height = 320;
  panel.offset_rotation = 0;
  panel.readable = false;
  panel.invert = invert;
  panel.rgb_order = false;
  panel.bus_shared = false;
  panel_.config(panel);
  setPanel(&panel_);
}

namespace {

BadgeLcd *lcd = nullptr;
LGFX_Sprite *sprite = nullptr;

}  // namespace

namespace display {

bool begin(bool invert, bool flip) {
  lcd = new BadgeLcd(invert);
  lcd->init();
  lcd->setRotation(flip ? 3 : 1);
  lcd->fillScreen(TFT_BLACK);
  sprite = new LGFX_Sprite(lcd);
  sprite->setColorDepth(8);
  return sprite->createSprite(board::SCREEN_W, board::SCREEN_H) != nullptr;
}

LGFX_Sprite &frame() { return *sprite; }

void present() { sprite->pushSprite(0, 0); }

}  // namespace display
