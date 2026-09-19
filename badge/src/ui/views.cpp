#include <Arduino.h>

#include "../link/robot_link.h"
#include "draw.h"

using namespace theme;

namespace ui::draw {

namespace {

constexpr int PANEL_H = BOTTOM - TOP;  // 108

/** Horizontal track for a value in [lo, hi], filled from the zero mark. */
void track(LGFX_Sprite &g, int x, int y, int w, float value, float lo, float hi, uint8_t fill) {
  g.drawRect(x, y, w, 8, HAIRLINE);
  const int zero = x + static_cast<int>(w * (-lo / (hi - lo)));
  const int at = x + static_cast<int>(w * ((constrain(value, lo, hi) - lo) / (hi - lo)));
  if (at != zero) g.fillRect(min(zero, at), y + 1, abs(at - zero), 6, fill);
  g.drawFastVLine(zero, y - 3, 14, INK_60);
}

/** Vertical track for a signed duty, filled up (forward) or down (reverse) from the middle. */
void column(LGFX_Sprite &g, int x, int y, int w, int h, float value) {
  g.drawRect(x, y, w, h, HAIRLINE);
  const int mid = y + h / 2;
  const int len = static_cast<int>(constrain(value, -1.0f, 1.0f) * (h / 2 - 1));
  if (len > 0) g.fillRect(x + 1, mid - len, w - 2, len, BLUE);
  if (len < 0) g.fillRect(x + 1, mid, w - 2, -len, INK);
  g.drawFastHLine(x - 3, mid, w + 6, INK_60);
}

void key(LGFX_Sprite &g, int cx, int cy, bool held) {
  if (held) g.fillRect(cx - 6, cy - 6, 13, 13, BLUE);
  else g.drawRect(cx - 6, cy - 6, 13, 13, HAIRLINE);
}

/** One selectable row: a panel with a blue marker on the left when selected. */
void row(LGFX_Sprite &g, int y, bool selected) {
  panel(g, 10, y, 300, 32);
  if (selected) g.fillRect(10, y, 4, 32, BLUE);
}

}  // namespace

void driveView(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const ButtonState &in = *m.input;
  char text[16];

  // D-pad panel: keys light while held; the square is the ramped stick command.
  panel(g, 10, TOP, 110, PANEL_H);
  label(g, "STICK", 18, TOP + 8, INK_60);
  const int cx = 65, cy = TOP + 62, r = 34;
  g.drawFastHLine(cx - r, cy, 2 * r + 1, HAIRLINE);
  g.drawFastVLine(cx, cy - r, 2 * r + 1, HAIRLINE);
  key(g, cx, cy - r, in.isHeld(Button::Up));
  key(g, cx, cy + r, in.isHeld(Button::Down));
  key(g, cx - r, cy, in.isHeld(Button::Left));
  key(g, cx + r, cy, in.isHeld(Button::Right));
  const int dx = cx + static_cast<int>(s.stickX * (r - 8));
  const int dy = cy - static_cast<int>(s.stickY * (r - 8));
  g.fillRect(dx - 5, dy - 5, 11, 11, m.controller->canMove() ? BLUE : INK_35);

  // Wheel duty, exactly what goes in the packet.
  const WheelDuty duty = m.controller->mix();
  panel(g, 126, TOP, 96, PANEL_H);
  label(g, "WHEELS", 134, TOP + 8, INK_60);
  column(g, 146, TOP + 24, 16, 60, duty.left);
  column(g, 186, TOP + 24, 16, 60, duty.right);
  snprintf(text, sizeof text, "%+.1f", duty.left);
  pixel(g, text, 154, TOP + 92, 1, INK, Align::Centre);
  snprintf(text, sizeof text, "%+.1f", duty.right);
  pixel(g, text, 194, TOP + 92, 1, INK, Align::Centre);

  // Speed limit: big pixel number and four step cells.
  panel(g, 228, TOP, 82, PANEL_H);
  label(g, "SPEED", 236, TOP + 8, INK_60);
  snprintf(text, sizeof text, "%d", static_cast<int>(s.speedLimit * 100 + 0.5f));
  pixel(g, text, 236, TOP + 28, 3, INK);
  label(g, "%", 238 + pixelWidth(text, 3), TOP + 42, INK_60);
  for (int i = 0; i < 4; i++) {
    const bool lit = s.speedLimit >= (i + 1) * 0.25f - 0.01f;
    if (lit) g.fillRect(236 + i * 17, TOP + 66, 14, 8, BLUE);
    else g.drawRect(236 + i * 17, TOP + 66, 14, 8, HAIRLINE);
  }
  label(g, "A CYCLE", 236, TOP + 88, INK_35);
}

void armView(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const uint8_t selected = m.controller->selectedJoint();
  char text[12];
  for (uint8_t i = 0; i < JointCount; i++) {
    const int y = TOP + i * 38;
    const bool on = i == selected;
    row(g, y, on);
    label(g, jointName(static_cast<Joint>(i)), 24, y + 13, on ? INK : INK_60);
    int lo, hi;
    jointLimits(static_cast<Joint>(i), lo, hi);
    track(g, 110, y + 12, 130, s.arm[i], lo, hi, on ? BLUE : INK_35);
    snprintf(text, sizeof text, "%+d", static_cast<int>(lroundf(s.arm[i])));
    pixel(g, text, 302, y + 8, 2, on ? INK : INK_60, Align::Right);
  }
}

void winchView(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const Telemetry &t = robotlink::telemetry();
  const uint8_t selected = m.controller->selectedWinch();
  char text[12];
  for (uint8_t i = 0; i < WINCH_COUNT; i++) {
    const int y = TOP + i * 38;
    const bool on = i == selected;
    row(g, y, on);
    snprintf(text, sizeof text, "WINCH %u", i + 1);
    label(g, text, 24, y + 13, on ? INK : INK_60);

    // Command chip: solid blue while running.
    const int8_t cmd = s.winch[i];
    const char *state = cmd < 0 ? "IN" : (cmd > 0 ? "OUT" : "HOLD");
    if (cmd) g.fillRect(96, y + 8, 40, 16, BLUE);
    else g.drawRect(96, y + 8, 40, 16, HAIRLINE);
    label(g, state, 116, y + 13, cmd ? WHITE : INK_60, Align::Centre);

    // Spool position (0 in .. 1 out) and the two end stops, from telemetry.
    g.drawRect(146, y + 12, 110, 8, HAIRLINE);
    if (!isnan(t.winchPos[i])) {
      g.fillRect(147, y + 13, static_cast<int>(108 * constrain(t.winchPos[i], 0.0f, 1.0f)), 6, on ? BLUE : INK_35);
    }
    for (int end = 0; end < 2; end++) {
      const int x = 270 + end * 16;
      if (t.limits[i][end]) g.fillRect(x, y + 11, 10, 10, SIGNAL);
      else g.drawRect(x, y + 11, 10, 10, HAIRLINE);
    }
  }
}

void setupView(LGFX_Sprite &g, const UiModel &m) {
  panel(g, 10, TOP, 300, PANEL_H);
  label(g, "CONNECT THE ROBOT", 22, TOP + 12, INK);
  label(g, "USB SERIAL 115200, THEN TYPE", 22, TOP + 30, INK_60);
  label(g, "WIFI HTN-ROBOT <PASSWORD>", 22, TOP + 50, BLUE);
  label(g, "URL WS://192.168.4.1:81/", 22, TOP + 66, BLUE);
  label(g, m.linkText, 22, TOP + 88, INK_35);
}

}  // namespace ui::draw
