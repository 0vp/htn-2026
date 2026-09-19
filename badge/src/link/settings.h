#pragma once

#include <Arduino.h>

#include "../hal/buttons.h"

/** Persistent settings, kept in NVS so they survive reflashing the app. */
struct Settings {
  String ssid;
  String password;
  /** Robot control socket, e.g. ws://robot.local:81/ — the same URL the dashboard uses. */
  String url;
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
 * USB serial console. Commands: help, status, wifi, url, lcd, datapin, map, polarity,
 * buttons, reboot. Returns true when the Wi-Fi or URL settings changed.
 */
bool pollConsole();

/** True while `buttons` monitoring is on; the main loop then prints raw shift bytes. */
bool monitoringButtons();

}  // namespace settings
