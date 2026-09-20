#include "ui.h"

#include <Arduino.h>

#include "../link/client.h"
#include "draw.h"

using namespace theme;
using namespace ui::draw;

namespace {

void nav(LGFX_Sprite &g, const UiModel &m) {
  g.fillRect(0, 0, 320, NAV_H, PAPER);
  g.setFont(&fonts::FreeSansBold9pt7b);
  g.setTextColor(INK);
  g.setTextDatum(middle_left);
  g.drawString("HTN Robot", 10, NAV_H / 2);
  label(g, m.linked ? "REMOTE" : "OFFLINE", 312, 10, m.linked ? BLUE : INK_35, Align::Right);
  g.drawFastHLine(0, NAV_H - 1, 320, HAIRLINE);
}

void stateBlock(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  Block block = Block::Blue;
  const char *word = "SAFE";
  const char *detail = "HOLD START TO ARM";
  if (s.estop) {
    block = Block::Signal;
    word = "E-STOP";
    detail = "RESET THE BASE BOARD";
  } else if (s.armed) {
    block = Block::Ok;
    word = "ARMED";
    detail = "B STOP  HOLD B E-STOP";
  }
  g.fillRect(0, BLOCK_Y, 320, BLOCK_H, blockColour(block));
  pixel(g, word, 12, BLOCK_Y + 14, 3, WHITE);
  label(g, detail, 310, BLOCK_Y + 14, WHITE, Align::Right);
  label(g, m.configured ? "D-PAD DRIVE  A SPEED" : "SET UP OVER USB", 310, BLOCK_Y + 28,
        band(block, 4), Align::Right);

  // Hold progress runs along the bottom edge: START towards arming, B towards a latching E-STOP.
  const float arming = s.armed ? 0.0f : m.controller->armProgress();
  const float hold = max(arming, m.controller->estopProgress());
  if (hold > 0) g.fillRect(0, BLOCK_Y + BLOCK_H - 4, static_cast<int>(320 * min(hold, 1.0f)), 4, WHITE);
  bands(g, block, BANDS_Y);
}

void footer(LGFX_Sprite &g, const UiModel &m) {
  g.fillRect(0, FOOTER_Y, 320, 240 - FOOTER_Y, PAPER);
  g.drawFastHLine(0, FOOTER_Y, 320, HAIRLINE);
  const int y = FOOTER_Y + 11;
  char text[40];

  // What this badge is asking for, before drive.py applies calibration.json and its own limit.
  const float linear = m.controller->linear(), angular = m.controller->angular();
  snprintf(text, sizeof text, "CMD %+.2f %+.2f", linear, angular);
  label(g, text, 10, y, linear == 0 && angular == 0 ? INK_35 : INK);

  // Link state, right-aligned with a square status light.
  uint8_t light = INK_35;
  switch (robotlink::status()) {
    case robotlink::Status::Linked:
      light = theme::OK;
      snprintf(text, sizeof text, "DRIVE.PY %d", m.wifiRssi);
      break;
    case robotlink::Status::Unconfigured:
      light = SIGNAL;
      snprintf(text, sizeof text, "%s", m.linkText);
      break;
    default:
      // Joining Wi-Fi and dialling drive.py are one waiting state to the operator; the console's
      // `status` still separates them when a link is actually being debugged.
      light = WARN;
      snprintf(text, sizeof text, "CONNECTING");
      break;
  }
  label(g, text, 310, y, INK, Align::Right);
  g.fillRect(310 - labelWidth(text) - 12, y, 7, 7, light);
}

}  // namespace

namespace ui {

void begin() { theme::begin(); }

void dumpFrame() {
  LGFX_Sprite &g = display::frame();
  const uint8_t *pixels = static_cast<const uint8_t *>(g.getBuffer());
  Serial.printf("SHOT %d %d %d\n", g.width(), g.height(), theme::COUNT);
  for (int i = 0; i < theme::COUNT; i++) Serial.printf("%06lX", static_cast<unsigned long>(theme::rgb(i)));
  Serial.println();
  char line[2 * 320 + 1];
  for (int y = 0; y < g.height(); y++) {
    for (int x = 0; x < g.width(); x++) sprintf(line + 2 * x, "%02X", pixels[y * g.width() + x]);
    Serial.println(line);
  }
  Serial.println("END");
}

void splash(const char *message) {
  LGFX_Sprite &g = display::frame();
  g.fillScreen(PAPER);
  dots(g, 0, 0, 320, 240);
  g.fillRect(0, 70, 320, 60, BLUE);
  pixel(g, "HTN ROBOT", 160, 84, 4, WHITE, Align::Centre);
  bands(g, Block::Blue, 130);
  label(g, message, 160, 160, INK_60, Align::Centre);
  display::present();
}

void render(const UiModel &m) {
  LGFX_Sprite &g = display::frame();
  g.fillScreen(PAPER);
  dots(g, 0, TOP - 6, 320, FOOTER_Y - TOP + 6);
  nav(g, m);
  stateBlock(g, m);
  if (!m.configured) setupView(g, m);
  else driveView(g, m);
  footer(g, m);
  display::present();
}

}  // namespace ui
