#include <Arduino.h>

#include "control/control.h"
#include "hal/buttons.h"
#include "hal/display.h"
#include "hal/leds.h"
#include "link/robot_link.h"
#include "link/settings.h"
#include "ui/ui.h"

namespace {

constexpr uint32_t PACKET_MS = 50;  // 20 Hz, same as the dashboard.
constexpr uint32_t FRAME_MS = 66;   // ~15 fps is plenty and leaves time for Wi-Fi.
constexpr int PROBE_PINS[] = {7, 8};  // GPIO0 is LCD D/C, never read it

Controller controller;
uint32_t seq = 0;
uint32_t lastPacket = 0, lastFrame = 0, lastTick = 0;
uint8_t lastProbe[2] = {0, 0};
bool lastStart = false;

void sendPacket() {
  char json[320];
  const size_t n = controller.packet(json, sizeof json, ++seq, robotlink::timestampMs());
  if (n) robotlink::send(json, n);
}

void updateLeds() {
  const ControlState &s = controller.state();
  if (s.estop) {
    leds::show(255, 0, 0, true);
  } else if (s.armed) {
    leds::show(0, 255, 60, false);
  } else if (robotlink::isOpen()) {
    leds::show(0, 90, 255, false);
  } else {
    leds::show(255, 140, 0, true);
  }
}

/** `buttons` console mode: print the raw shift byte on each candidate data pin as it changes. */
void probeButtons(const ButtonState &st) {
  bool changed = false;
  uint8_t now[2];
  for (int i = 0; i < 2; i++) {
    if (PROBE_PINS[i] != buttons::map().dataPin) pinMode(PROBE_PINS[i], INPUT);
    now[i] = buttons::readRaw(PROBE_PINS[i]);
    changed |= now[i] != lastProbe[i];
  }
  const bool start = digitalRead(9) == LOW;
  changed |= start != lastStart;
  if (!changed) return;
  lastStart = start;
  memcpy(lastProbe, now, sizeof now);
  Serial.printf("raw gpio7=%02X gpio8=%02X start=%d  held:", now[0], now[1], start);
  for (uint8_t b = 0; b < BUTTON_COUNT; b++) {
    if (st.isHeld(static_cast<Button>(b))) Serial.printf(" %s", buttonName(static_cast<Button>(b)));
  }
  Serial.println();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  settings::load();
  Settings &cfg = settings::get();

  if (!display::begin(cfg.invertLcd, cfg.flipLcd)) Serial.println("frame buffer allocation failed");
  ui::splash("starting...");
  leds::begin();
  buttons::begin(cfg.buttons);
  robotlink::begin(cfg);

  Serial.println("\nrobot controller ready. type 'help'.");
  lastTick = millis();
}

void loop() {
  if (settings::pollConsole()) robotlink::reconfigure(settings::get());
  robotlink::loop();

  const uint32_t now = millis();
  const float dt = (now - lastTick) / 1000.0f;
  lastTick = now;

  const ButtonState &input = buttons::poll();
  controller.update(input, dt, robotlink::isOpen());
  if (settings::monitoringButtons()) probeButtons(input);

  if (now - lastPacket >= PACKET_MS) {
    lastPacket = now;
    sendPacket();
  }

  if (now - lastFrame >= FRAME_MS) {
    lastFrame = now;
    const Settings &cfg = settings::get();
    const UiModel model{&controller,
                        &input,
                        robotlink::statusText(),
                        robotlink::isOpen(),
                        cfg.ssid.length() > 0 && cfg.url.length() > 0,
                        robotlink::wifiRssi(),
                        robotlink::silenceMs()};
    ui::render(model);
  }

  updateLeds();
  leds::tick();
  delay(1);
}
