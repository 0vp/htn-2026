#pragma once

#include <Arduino.h>

#include "../hal/buttons.h"

/** Persistent settings, kept in NVS so they survive reflashing the app. */
struct Settings {
  String ssid;
  String password;
  /** Shared secret the agent must present: ws://<badge-ip>:81/?token=... */
  String token;
  bool invertLcd = true;
  /** Rotates the landscape screen 180 degrees. */
  bool flipLcd = false;
  ButtonMap buttons;
};

namespace settings {

Settings &get();
void load();
void save();

/**
 * USB serial console. Commands: help, status, wifi, token, lcd, datapin, map, polarity,
 * buttons, reboot. Returns true when the Wi-Fi or token settings changed.
 */
bool pollConsole();

/** True while `buttons` monitoring is on; the main loop then prints raw shift bytes. */
bool monitoringButtons();

/** True once after `shot` was typed; the main loop then dumps the frame. */
bool takeShotRequest();

/** Mode index (0 drive, 1 auto) once after `mode` was typed, else -1. */
int takeModeRequest();

}  // namespace settings
