#include <Arduino.h>

#include "control/control.h"
#include "hal/buttons.h"
#include "hal/display.h"
#include "hal/motor.h"
#include "link/server.h"
#include "link/settings.h"
#include "ui/ui.h"

namespace {

constexpr uint32_t MOTOR_MS = 5;   // 200 Hz outputs and watchdog
constexpr uint32_t FRAME_MS = 66;  // ~15 fps is plenty and leaves time for Wi-Fi
constexpr UBaseType_t MOTOR_PRIORITY = 5;  // above the Arduino loop, so a stop is never delayed
constexpr int PROBE_PINS[] = {7, 8};       // GPIO0 is LCD D/C, never read it

Controller controller;
uint32_t lastFrame = 0, lastTick = 0;
uint8_t lastProbe[2] = {0, 0};
bool lastStart = false;

/** The only code that drives the motor and servo; commands expire here, not in the network. */
void motorTask(void *) {
  TickType_t wake = xTaskGetTickCount();
  uint32_t last = millis();
  for (;;) {
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(MOTOR_MS));
    const uint32_t now = millis();
    const float dt = (now - last) / 1000.0f;
    last = now;
    float duty = 0, steering = 0;
    if (robotserver::snapshot(duty, steering)) {
      motor::apply(duty, steering, dt);
    } else {
      // Expired, disarmed or stopped: cut drive at once and hold the steering angle.
      motor::stop();
      motor::apply(0, steering, dt);
    }
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

  // Outputs first, so the motor pins are driven low before anything else runs.
  motor::begin();
  if (!display::begin(cfg.invertLcd, cfg.flipLcd)) Serial.println("frame buffer allocation failed");
  ui::begin();
  ui::splash("starting...");
  buttons::begin(cfg.buttons);
  robotserver::begin(cfg);
  xTaskCreate(motorTask, "motor", 4096, nullptr, MOTOR_PRIORITY, nullptr);

  Serial.println("\nrobot controller ready. type 'help'.");
  lastTick = millis();
}

void loop() {
  if (settings::pollConsole()) robotserver::reconfigure(settings::get());

  const uint32_t now = millis();
  const float dt = (now - lastTick) / 1000.0f;
  lastTick = now;

  const ButtonState &input = buttons::poll();
  controller.update(input, dt);
  if (settings::monitoringButtons()) probeButtons(input);
  const int mode = settings::takeModeRequest();
  if (mode >= 0) controller.setMode(static_cast<Mode>(mode));

  // The badge's own buttons are the only way to grant supervision or clear an E-STOP.
  const ControlState &state = controller.state();
  if (state.estop) {
    robotserver::emergencyStop();
  } else if (state.armed) {
    robotserver::clearEstop();
  }
  robotserver::supervise(controller.supervising());
  robotserver::setLocal(controller.driving(), controller.duty(), controller.steering());

  if (now - lastFrame >= FRAME_MS) {
    lastFrame = now;
    const Settings &cfg = settings::get();
    const UiModel model{&controller,
                        &input,
                        robotserver::statusText(),
                        robotserver::clientCount() > 0,
                        cfg.ssid.length() > 0 && cfg.token.length() > 0,
                        robotserver::wifiRssi(),
                        robotserver::agentSilenceMs()};
    ui::render(model);
    if (settings::takeShotRequest()) ui::dumpFrame();
  }
  delay(1);
}
