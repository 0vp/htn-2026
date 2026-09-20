#pragma once

#include <Arduino.h>

#include "../hal/buttons.h"

/** Persistent settings, kept in NVS so they survive reflashing the app. */
struct Settings {
  String ssid;
  String password;
  /** Where drive.py listens, e.g. ws://192.168.1.20:8793/ (no token in the URL needed). */
  String url;
  /** Shared secret drive.py was started with (--token); appended to `url` when dialling. */
  String token;
  /** Drive over the USB cable (`drive.py --badge <port>`) instead of Wi-Fi; radio stays off. */
  bool usb = false;
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
 * USB serial console. Commands: help, status, link, wifi, url, token, lcd, datapin, map,
 * polarity, buttons, reboot. A line starting with `{` is drive.py telemetry on the USB
 * transport, not a command, and goes straight to robotlink::feedTelemetry().
 * Returns true when the transport, Wi-Fi, URL or token settings changed.
 */
bool pollConsole();

/** True while `buttons` monitoring is on; the main loop then prints raw shift bytes. */
bool monitoringButtons();

/** True once after `shot` was typed; the main loop then dumps the frame. */
bool takeShotRequest();

}  // namespace settings
