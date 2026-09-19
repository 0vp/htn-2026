#include "ui.h"

#include <Arduino.h>

#include "../link/robot_link.h"
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

  // Mode tabs, right-aligned; the active one is a solid blue block like the dashboard's button.
  int x = 312;
  for (int i = static_cast<int>(Mode::Count) - 1; i >= 0; i--) {
    const char *name = modeName(static_cast<Mode>(i));
    const int w = labelWidth(name) + 14;
    x -= w;
    const bool on = static_cast<Mode>(i) == m.controller->mode();
    if (on) g.fillRect(x, 5, w, NAV_H - 10, BLUE);
    label(g, name, x + 7, 10, on ? WHITE : INK_60);
    x -= 4;
  }
  g.drawFastHLine(0, NAV_H - 1, 320, HAIRLINE);
}

const char *modeHint(Mode mode) {
  switch (mode) {
    case Mode::Drive:
      return "D-PAD DRIVE  A SPEED";
    case Mode::Arm:
      return "L/R JOINT  U/D MOVE";
    case Mode::Auto:
      return "AGENT DRIVES";
    default:
      return "L/R WINCH  U IN  D OUT";
  }
}

void stateBlock(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  Block block = Block::Blue;
  const char *word = "SAFE";
  const char *detail = m.linkOpen ? "HOLD START TO ARM" : "WAITING FOR ROBOT";
  if (s.estop) {
    block = Block::Signal;
    word = "E-STOP";
    detail = m.linkOpen ? "HOLD START TO CLEAR" : "WAITING FOR ROBOT";
  } else if (m.controller->supervising()) {
    block = Block::Ok;
    word = "AUTO";
    detail = "ANY BUTTON STOPS";
  } else if (s.armed) {
    block = Block::Ok;
    word = "ARMED";
    detail = "B STOP  START DISARM";
  }
  g.fillRect(0, BLOCK_Y, 320, BLOCK_H, blockColour(block));
  pixel(g, word, 12, BLOCK_Y + 14, 3, WHITE);
  label(g, detail, 310, BLOCK_Y + 14, WHITE, Align::Right);
  label(g, m.configured ? modeHint(m.controller->mode()) : "SET UP OVER USB", 310, BLOCK_Y + 28, band(block, 4),
        Align::Right);

  // Arming progress runs along the bottom edge of the block while START is held.
  const float hold = m.controller->armProgress();
  if (hold > 0 && !s.armed) g.fillRect(0, BLOCK_Y + BLOCK_H - 4, static_cast<int>(320 * min(hold, 1.0f)), 4, WHITE);
  bands(g, block, BANDS_Y);
}

void footer(LGFX_Sprite &g, const UiModel &m) {
  const Telemetry &t = robotlink::telemetry();
  g.fillRect(0, FOOTER_Y, 320, 240 - FOOTER_Y, PAPER);
  g.drawFastHLine(0, FOOTER_Y, 320, HAIRLINE);
  const int y = FOOTER_Y + 11;
  char text[40];

  // Battery: five square cells, like a meter, then the pack voltage.
  if (!isnan(t.packVolts) && t.packVolts > 1) {
    const float soc = stateOfCharge(t.packVolts);
    const uint8_t fill = soc < 0.2f ? SIGNAL : (soc < 0.4f ? WARN : theme::OK);
    for (int i = 0; i < 5; i++) {
      const bool lit = soc > i * 0.2f + 0.05f;
      if (lit) g.fillRect(10 + i * 7, y - 1, 5, 9, fill);
      else g.drawRect(10 + i * 7, y - 1, 5, 9, HAIRLINE);
    }
    snprintf(text, sizeof text, "%.1fV", t.packVolts);
    label(g, text, 50, y, INK);
  } else {
    label(g, "BATT --", 10, y, INK_35);
  }

  if (!isnan(t.rpmLeft) || !isnan(t.rpmRight)) {
    snprintf(text, sizeof text, "RPM %.0f/%.0f", isnan(t.rpmLeft) ? 0 : t.rpmLeft, isnan(t.rpmRight) ? 0 : t.rpmRight);
    label(g, text, 104, y, INK_60);
  }

  // Link state, right-aligned with a square status light.
  uint8_t light = INK_35;
  switch (robotlink::status()) {
    case robotlink::Status::Open:
      light = theme::OK;
      snprintf(text, sizeof text, "ONLINE %d", m.wifiRssi);
      break;
    case robotlink::Status::Silent:
      light = SIGNAL;
      snprintf(text, sizeof text, "ROBOT SILENT");
      break;
    case robotlink::Status::Unconfigured:
      light = SIGNAL;
      snprintf(text, sizeof text, "%s", m.linkText);
      break;
    default:
      light = WARN;
      snprintf(text, sizeof text, "%s", m.linkText);
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
  if (!m.configured) {
    setupView(g, m);
  } else {
    switch (m.controller->mode()) {
      case Mode::Drive:
        driveView(g, m);
        break;
      case Mode::Arm:
        armView(g, m);
        break;
      case Mode::Auto:
        autoView(g, m);
        break;
      default:
        winchView(g, m);
        break;
    }
  }
  footer(g, m);
  display::present();
}

}  // namespace ui
