#include <Arduino.h>
#include <string.h>

#include "../hal/motor.h"
#include "../link/server.h"
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

/** Applied motor output: duty column, steering track and the numbers, as the wheel sees them. */
void outputPanel(LGFX_Sprite &g, int x, int w) {
  panel(g, x, TOP, w, PANEL_H);
  label(g, "OUTPUT", x + 8, TOP + 8, INK_60);
  const float duty = motor::appliedDuty();
  // Full column height is the 30% duty limit, so small commands stay readable.
  column(g, x + 14, TOP + 24, 16, 60, duty / MAX_DUTY);
  char text[12];
  snprintf(text, sizeof text, "%+.2f", duty);
  pixel(g, text, x + 22, TOP + 92, 1, INK, Align::Centre);
  label(g, "STEER", x + 46, TOP + 24, INK_60);
  track(g, x + 46, TOP + 40, w - 58, motor::appliedSteering(), -MAX_STEERING_DEG, MAX_STEERING_DEG,
        BLUE);
  snprintf(text, sizeof text, "%+.0f", motor::appliedSteering());
  pixel(g, text, x + w - 10, TOP + 60, 2, INK, Align::Right);
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

  outputPanel(g, 126, 96 + 40);

  // Speed limit: big pixel number and four step cells.
  panel(g, 268, TOP, 42, PANEL_H);
  label(g, "SPD", 276, TOP + 8, INK_60);
  snprintf(text, sizeof text, "%d", static_cast<int>(s.speedLimit * 100 + 0.5f));
  pixel(g, text, 276, TOP + 26, 2, INK);
  for (int i = 0; i < 4; i++) {
    const bool lit = s.speedLimit >= (i + 1) * 0.25f - 0.01f;
    if (lit) g.fillRect(276, TOP + 52 + i * 12, 26, 8, BLUE);
    else g.drawRect(276, TOP + 52 + i * 12, 26, 8, HAIRLINE);
  }
  label(g, "A", 276, TOP + 100, INK_35);
}

void autoView(LGFX_Sprite &g, const UiModel &m) {
  const bool agent = strcmp(robotserver::owner(), "agent") == 0;

  panel(g, 10, TOP, 186, PANEL_H);
  label(g, "AGENT", 18, TOP + 8, INK_60);
  pixel(g, agent ? "DRIVING" : "IDLE", 18, TOP + 26, 2, agent ? BLUE : INK_35);
  const bool supervising = m.controller->supervising();
  g.fillRect(18, TOP + 56, 7, 7, supervising ? theme::OK : INK_35);
  label(g, supervising ? "SUPERVISED" : "NOT SUPERVISED", 30, TOP + 56, INK);
  label(g, supervising ? "PRESS ANY BUTTON TO STOP" : "HOLD START TO ALLOW", 18, TOP + 76, INK_60);
  if (!supervising) label(g, "THE AGENT TO DRIVE", 18, TOP + 88, INK_60);

  outputPanel(g, 202, 108);
}

void setupView(LGFX_Sprite &g, const UiModel &m) {
  panel(g, 10, TOP, 300, PANEL_H);
  label(g, "CONNECT THE AGENT", 22, TOP + 12, INK);
  label(g, "USB SERIAL 115200, THEN TYPE", 22, TOP + 30, INK_60);
  label(g, "WIFI <SSID> <PASSWORD>", 22, TOP + 50, BLUE);
  label(g, "TOKEN <SECRET>", 22, TOP + 66, BLUE);
  label(g, m.linkText, 22, TOP + 88, INK_35);
}

}  // namespace ui::draw
