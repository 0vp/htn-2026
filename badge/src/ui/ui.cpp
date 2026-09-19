#include "ui.h"

#include <Arduino.h>

#include "../link/robot_link.h"
#include "draw.h"

using namespace ui::draw;

namespace {

void header(LGFX_Sprite &g, const UiModel &m) {
  g.fillRect(0, 0, 320, 28, PANEL);
  const Mode active = m.controller->mode();
  g.setFont(&fonts::FreeSansBold9pt7b);
  g.setTextDatum(middle_center);
  for (uint8_t i = 0; i < static_cast<uint8_t>(Mode::Count); i++) {
    const int x = 4 + i * 66;
    const bool on = static_cast<Mode>(i) == active;
    if (on) g.fillRoundRect(x, 3, 62, 22, 5, ACCENT);
    g.setTextColor(on ? BG : MUTED);
    g.drawString(modeName(static_cast<Mode>(i)), x + 31, 15);
  }

  // Link pill on the right.
  const uint16_t dot = m.linkOpen ? GO : (m.configured ? WARN : STOP);
  g.setFont(&fonts::Font2);
  g.setTextDatum(middle_right);
  g.setTextColor(TEXT);
  char text[40];
  if (m.linkOpen && m.wifiRssi) {
    snprintf(text, sizeof text, "%s %ddB", m.linkText, m.wifiRssi);
  } else {
    snprintf(text, sizeof text, "%s", m.linkText);
  }
  g.drawString(text, 314, 15);
  g.fillCircle(314 - g.textWidth(text) - 9, 14, 5, dot);
}

void banner(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const float hold = m.controller->armProgress();
  uint16_t fill = PANEL;
  const char *title = "SAFE";
  const char *detail = m.linkOpen ? "hold START to arm" : "waiting for robot link";
  if (s.estop) {
    fill = STOP;
    title = "E-STOP";
    detail = m.linkOpen ? "hold START to clear + arm" : "link down";
  } else if (s.armed) {
    fill = GO;
    title = "ARMED";
    detail = "B = stop   START = disarm";
  }
  g.fillRoundRect(4, 32, 312, 30, 6, fill);
  if (hold > 0 && !s.armed) {
    g.fillRoundRect(4, 32, static_cast<int>(312 * min(hold, 1.0f)), 30, 6, GO);
  }
  g.setTextColor(s.estop || s.armed ? BG : TEXT);
  g.setFont(&fonts::FreeSansBold12pt7b);
  g.setTextDatum(middle_left);
  g.drawString(title, 14, 48);
  g.setFont(&fonts::Font2);
  g.setTextDatum(middle_right);
  g.drawString(detail, 308, 48);
}

void footer(LGFX_Sprite &g, const UiModel &m) {
  const Telemetry &t = robotlink::telemetry();
  g.drawFastHLine(0, BOTTOM + 2, 320, LINE);
  g.setFont(&fonts::Font2);
  g.setTextDatum(middle_left);
  char text[64];

  // Robot battery, if the robot reports it.
  if (!isnan(t.packVolts)) {
    const float soc = stateOfCharge(t.packVolts);
    const uint16_t c = soc < 0.2f ? STOP : (soc < 0.4f ? WARN : GO);
    g.drawRect(6, 214, 28, 14, MUTED);
    g.fillRect(34, 218, 2, 6, MUTED);
    g.fillRect(8, 216, static_cast<int>(24 * soc), 10, c);
    snprintf(text, sizeof text, "%.1fV %d%%", t.packVolts, static_cast<int>(soc * 100));
    g.setTextColor(TEXT);
    g.drawString(text, 40, 221);
  } else {
    g.setTextColor(MUTED);
    g.drawString("battery --", 6, 221);
  }

  if (!isnan(t.rpmLeft) || !isnan(t.rpmRight)) {
    snprintf(text, sizeof text, "rpm %.0f/%.0f", isnan(t.rpmLeft) ? 0 : t.rpmLeft, isnan(t.rpmRight) ? 0 : t.rpmRight);
    g.setTextColor(TEXT);
    g.drawString(text, 122, 221);
  }

  // How long since the robot last spoke; the robot doesn't have to talk back.
  g.setTextDatum(middle_right);
  if (m.linkOpen && m.robotSilenceMs != UINT32_MAX) {
    const bool stale = m.robotSilenceMs > 1500;
    snprintf(text, sizeof text, stale ? "rx %lus ago" : "rx live", static_cast<unsigned long>(m.robotSilenceMs / 1000));
    g.setTextColor(stale ? WARN : GO);
  } else {
    snprintf(text, sizeof text, "HOME: mode");
    g.setTextColor(MUTED);
  }
  g.drawString(text, 314, 221);
}

}  // namespace

namespace ui {

void splash(const char *message) {
  LGFX_Sprite &g = display::frame();
  g.fillScreen(BG);
  g.setTextColor(TEXT);
  g.setTextDatum(middle_center);
  g.setFont(&fonts::FreeSansBold12pt7b);
  g.drawString("ROBOT CONTROLLER", 160, 100);
  g.setFont(&fonts::Font2);
  g.setTextColor(MUTED);
  g.drawString(message, 160, 136);
  display::present();
}

void render(const UiModel &m) {
  LGFX_Sprite &g = display::frame();
  g.fillScreen(BG);
  header(g, m);
  banner(g, m);
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
      default:
        winchView(g, m);
        break;
    }
  }
  footer(g, m);
  display::present();
}

}  // namespace ui
