#include <Arduino.h>

#include "../link/robot_link.h"
#include "draw.h"

namespace ui::draw {

void centredBar(LGFX_Sprite &g, int x, int y, int w, int h, float value, float lo, float hi, uint16_t colour) {
  g.fillRoundRect(x, y, w, h, 3, PANEL);
  const int zero = x + static_cast<int>(w * (-lo / (hi - lo)));
  const int at = x + static_cast<int>(w * ((constrain(value, lo, hi) - lo) / (hi - lo)));
  g.fillRect(min(zero, at), y, abs(at - zero) + 1, h, colour);
  g.drawFastVLine(zero, y - 2, h + 4, MUTED);
}

void signedColumn(LGFX_Sprite &g, int x, int y, int w, int h, float value, uint16_t colour) {
  g.fillRoundRect(x, y, w, h, 3, PANEL);
  const int mid = y + h / 2;
  const int len = static_cast<int>(constrain(value, -1.0f, 1.0f) * (h / 2));
  if (len > 0) g.fillRect(x, mid - len, w, len, colour);
  if (len < 0) g.fillRect(x, mid, w, -len, colour);
  g.drawFastHLine(x - 2, mid, w + 4, MUTED);
}

namespace {

void hint(LGFX_Sprite &g, const char *text) {
  g.setFont(&fonts::Font2);
  g.setTextDatum(bottom_center);
  g.setTextColor(MUTED);
  g.drawString(text, 160, BOTTOM);
}

void dpadKey(LGFX_Sprite &g, int x, int y, bool held) {
  g.fillRoundRect(x - 11, y - 11, 22, 22, 4, held ? ACCENT : PANEL);
}

}  // namespace

void driveView(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const ButtonState &in = *m.input;

  // Stick pad: the dot is the ramped command, the keys light while held.
  const int cx = 70, cy = 132, r = 52;
  g.drawCircle(cx, cy, r, LINE);
  dpadKey(g, cx, cy - r, in.isHeld(Button::Up));
  dpadKey(g, cx, cy + r, in.isHeld(Button::Down));
  dpadKey(g, cx - r, cy, in.isHeld(Button::Left));
  dpadKey(g, cx + r, cy, in.isHeld(Button::Right));
  const int dx = cx + static_cast<int>(s.stickX * (r - 14));
  const int dy = cy - static_cast<int>(s.stickY * (r - 14));
  g.drawLine(cx, cy, dx, dy, LINE);
  g.fillCircle(dx, dy, 9, m.controller->canMove() ? GO : MUTED);

  // Wheel duty columns, exactly what goes in the packet.
  const WheelDuty duty = m.controller->mix();
  g.setFont(&fonts::Font2);
  g.setTextDatum(top_center);
  g.setTextColor(MUTED);
  g.drawString("LEFT", 162, TOP + 4);
  g.drawString("RIGHT", 212, TOP + 4);
  signedColumn(g, 150, TOP + 22, 24, 90, duty.left, duty.left >= 0 ? GO : WARN);
  signedColumn(g, 200, TOP + 22, 24, 90, duty.right, duty.right >= 0 ? GO : WARN);
  char text[16];
  g.setTextColor(TEXT);
  snprintf(text, sizeof text, "%+.2f", duty.left);
  g.drawString(text, 162, TOP + 116);
  snprintf(text, sizeof text, "%+.2f", duty.right);
  g.drawString(text, 212, TOP + 116);

  // Speed limit.
  g.setTextDatum(top_center);
  g.setTextColor(MUTED);
  g.drawString("SPEED", 280, TOP + 4);
  g.setFont(&fonts::FreeSansBold18pt7b);
  g.setTextColor(ACCENT);
  snprintf(text, sizeof text, "%d", static_cast<int>(s.speedLimit * 100 + 0.5f));
  g.drawString(text, 280, TOP + 26);
  g.setFont(&fonts::Font2);
  g.setTextColor(MUTED);
  g.drawString("% (A)", 280, TOP + 62);
  hint(g, "D-pad drive   A speed   B stop");
}

void armView(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const uint8_t selected = m.controller->selectedJoint();
  for (uint8_t i = 0; i < JointCount; i++) {
    const int y = TOP + 6 + i * 40;
    const bool on = i == selected;
    if (on) g.drawRoundRect(4, y - 4, 312, 36, 6, ACCENT);
    int lo, hi;
    jointLimits(static_cast<Joint>(i), lo, hi);
    g.setFont(&fonts::FreeSansBold9pt7b);
    g.setTextDatum(middle_left);
    g.setTextColor(on ? TEXT : MUTED);
    g.drawString(jointName(static_cast<Joint>(i)), 14, y + 14);
    centredBar(g, 104, y + 8, 150, 12, s.arm[i], lo, hi, on ? ACCENT : LINE);
    char text[12];
    snprintf(text, sizeof text, "%+d", static_cast<int>(lroundf(s.arm[i])));
    g.setTextDatum(middle_right);
    g.drawString(text, 306, y + 14);
  }
  hint(g, m.controller->canMove() ? "L/R joint   Up/Dn move   A centre" : "arm to move joints");
}

void winchView(LGFX_Sprite &g, const UiModel &m) {
  const ControlState &s = m.controller->state();
  const Telemetry &t = robotlink::telemetry();
  const uint8_t selected = m.controller->selectedWinch();
  for (uint8_t i = 0; i < WINCH_COUNT; i++) {
    const int y = TOP + 6 + i * 40;
    const bool on = i == selected;
    if (on) g.drawRoundRect(4, y - 4, 312, 36, 6, ACCENT);
    char text[16];
    snprintf(text, sizeof text, "WINCH %u", i + 1);
    g.setFont(&fonts::FreeSansBold9pt7b);
    g.setTextDatum(middle_left);
    g.setTextColor(on ? TEXT : MUTED);
    g.drawString(text, 14, y + 14);

    const int8_t cmd = s.winch[i];
    const char *label = cmd < 0 ? "IN" : (cmd > 0 ? "OUT" : "HOLD");
    g.fillRoundRect(104, y + 3, 50, 22, 4, cmd ? GO : PANEL);
    g.setFont(&fonts::Font2);
    g.setTextDatum(middle_center);
    g.setTextColor(cmd ? BG : MUTED);
    g.drawString(label, 129, y + 14);

    // Spool position (0 in .. 1 out) and end stops, from telemetry when the robot sends it.
    g.fillRoundRect(164, y + 8, 100, 12, 3, PANEL);
    if (!isnan(t.winchPos[i])) g.fillRect(164, y + 8, static_cast<int>(100 * constrain(t.winchPos[i], 0.0f, 1.0f)), 12, LINE);
    g.fillCircle(280, y + 14, 6, t.limits[i][0] ? WARN : PANEL);
    g.fillCircle(300, y + 14, 6, t.limits[i][1] ? WARN : PANEL);
  }
  hint(g, m.controller->canMove() ? "L/R winch   Up reel in   Dn pay out" : "arm to run winches");
}

void setupView(LGFX_Sprite &g, const UiModel &m) {
  g.setFont(&fonts::FreeSansBold9pt7b);
  g.setTextDatum(top_left);
  g.setTextColor(TEXT);
  g.drawString("Connect the robot", 14, TOP + 6);
  g.setFont(&fonts::Font2);
  g.setTextColor(MUTED);
  g.drawString("Plug the badge into USB, open a serial", 14, TOP + 34);
  g.drawString("monitor at 115200 and type:", 14, TOP + 52);
  g.setTextColor(ACCENT);
  g.drawString("wifi htn-robot <password>", 24, TOP + 78);
  g.drawString("url ws://192.168.4.1:81/", 24, TOP + 98);
  g.setTextColor(MUTED);
  g.drawString(m.linkText, 14, TOP + 124);
}

}  // namespace ui::draw
