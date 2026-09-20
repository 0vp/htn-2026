#include <Arduino.h>
#include <string.h>

#include "draw.h"

using namespace theme;

namespace ui::draw {

namespace {

constexpr int PANEL_H = BOTTOM - TOP;  // 108
// Full column height. The base firmware caps raw duty well below this, so commands stay readable.
constexpr float DUTY_SCALE = 0.3f;

/** Vertical track for a signed duty, filled up (forward) or down (reverse) from the middle. */
void column(LGFX_Sprite &g, int x, int y, int w, int h, float value, bool live) {
  g.drawRect(x, y, w, h, HAIRLINE);
  const int mid = y + h / 2;
  const int len = static_cast<int>(constrain(value, -1.0f, 1.0f) * (h / 2 - 1));
  if (len > 0) g.fillRect(x + 1, mid - len, w - 2, len, live ? BLUE : INK_35);
  if (len < 0) g.fillRect(x + 1, mid, w - 2, -len, live ? INK : INK_35);
  g.drawFastHLine(x - 3, mid, w + 6, INK_60);
}

void key(LGFX_Sprite &g, int cx, int cy, bool held) {
  if (held) g.fillRect(cx - 6, cy - 6, 13, 13, BLUE);
  else g.drawRect(cx - 6, cy - 6, 13, 13, HAIRLINE);
}

/**
 * What the base is actually doing, from drive.py's telemetry: the two wheel duties after
 * calibration, and which controller it is obeying (keyboard, this badge, or nothing).
 */
void wheelsPanel(LGFX_Sprite &g, int x, int w, const UiModel &m) {
  panel(g, x, TOP, w, PANEL_H);
  label(g, "BASE", x + 8, TOP + 8, INK_60);
  if (!m.robot.valid) {
    pixel(g, "NO", x + 8, TOP + 34, 2, INK_35);
    pixel(g, "LINK", x + 8, TOP + 56, 2, INK_35);
    return;
  }
  char text[12];
  const float duties[] = {m.robot.left, m.robot.right};
  const char *const names[] = {"L", "R"};
  for (int i = 0; i < 2; i++) {
    const int cx = x + 16 + i * 34;
    label(g, names[i], cx + 4, TOP + 24, INK_60);
    column(g, cx, TOP + 36, 16, 48, duties[i] / DUTY_SCALE, duties[i] != 0);
    snprintf(text, sizeof text, "%+.2f", duties[i]);
    label(g, text, cx + 8, TOP + 90, INK, Align::Centre);
  }
  // drive.py's own arrow keys outrank the badge, so say plainly who has the wheel.
  const bool ours = strcmp(m.robot.source, "app") == 0;
  label(g, "OBEYING", x + 88, TOP + 24, INK_60);
  const char *who = strcmp(m.robot.source, "keyboard") == 0 ? "LAPTOP" : (ours ? "BADGE" : "IDLE");
  pixel(g, who, x + 88, TOP + 38, 2, ours ? BLUE : INK_60);
  snprintf(text, sizeof text, "TRIM %.2f/%.2f", m.robot.trimLeft, m.robot.trimRight);
  label(g, text, x + 88, TOP + 66, INK_35);
  if (m.robot.estop) label(g, "BASE E-STOP", x + 88, TOP + 84, SIGNAL);
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

  wheelsPanel(g, 126, 136, m);

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
  const bool agent = m.robot.valid && strcmp(m.robot.owner, "agent") == 0;

  panel(g, 10, TOP, 110, PANEL_H);
  label(g, "AGENT", 18, TOP + 8, INK_60);
  pixel(g, agent ? "DRIVING" : "IDLE", 18, TOP + 26, 1, agent ? BLUE : INK_35);
  const bool supervising = m.controller->supervising();
  g.fillRect(18, TOP + 50, 7, 7, supervising ? theme::OK : INK_35);
  label(g, supervising ? "ALLOWED" : "BLOCKED", 30, TOP + 50, INK);
  label(g, supervising ? "ANY BUTTON" : "HOLD START", 18, TOP + 72, INK_60);
  label(g, supervising ? "STOPS IT" : "TO ALLOW", 18, TOP + 84, INK_60);

  wheelsPanel(g, 126, 184, m);
}

void setupView(LGFX_Sprite &g, const UiModel &m) {
  panel(g, 10, TOP, 300, PANEL_H);
  label(g, "POINT THE BADGE AT DRIVE.PY", 22, TOP + 12, INK);
  label(g, "USB SERIAL 115200, THEN TYPE", 22, TOP + 30, INK_60);
  label(g, "WIFI <SSID> <PASSWORD>", 22, TOP + 48, BLUE);
  label(g, "URL WS://<LAPTOP-IP>:8793/", 22, TOP + 62, BLUE);
  label(g, "TOKEN <SECRET>", 22, TOP + 76, BLUE);
  label(g, m.linkText, 22, TOP + 94, INK_35);
}

}  // namespace ui::draw
