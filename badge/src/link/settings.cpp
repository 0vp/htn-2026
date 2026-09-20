#include "settings.h"

#include <Preferences.h>
#include <WiFi.h>

#include "../board.h"
#include "client.h"

namespace {

Settings current;
Preferences prefs;
String line;
bool monitor = false;
bool shotRequested = false;

constexpr const char *NS = "badgectl";

/** Splits off the next token; double quotes allow spaces (for SSIDs). */
String nextToken(String &rest) {
  rest.trim();
  String token;
  if (rest.startsWith("\"")) {
    const int end = rest.indexOf('"', 1);
    token = end < 0 ? rest.substring(1) : rest.substring(1, end);
    rest = end < 0 ? "" : rest.substring(end + 1);
  } else {
    const int end = rest.indexOf(' ');
    token = end < 0 ? rest : rest.substring(0, end);
    rest = end < 0 ? "" : rest.substring(end + 1);
  }
  return token;
}

void printStatus() {
  const ButtonMap &m = current.buttons;
  Serial.printf("wifi ssid: %s (%s)\n", current.ssid.length() ? current.ssid.c_str() : "<unset>",
                current.password.length() ? "password set" : "open");
  Serial.printf("transport: %s\n", current.usb ? "usb cable" : "wifi");
  Serial.printf("drive.py url: %s\n", current.url.length() ? current.url.c_str() : "<unset>");
  Serial.printf("token: %s\n", current.token.length() ? "set" : "<unset>");
  Serial.printf("wifi status code: %d\n", WiFi.status());
  Serial.printf("link: %s, badge ip %s, telemetry %lu ms ago\n", robotlink::statusText(),
                robotlink::localIp().c_str(),
                static_cast<unsigned long>(robotlink::telemetrySilenceMs()));
  Serial.printf("lcd invert: %d, flip: %d\n", current.invertLcd, current.flipLcd);
  Serial.printf("buttons: data GPIO%d, active %s, map", m.dataPin, m.activeHigh ? "high" : "low");
  for (uint8_t i = 0; i < 8; i++) Serial.printf(" %s=%u", buttonName(static_cast<Button>(i)), m.bitOf[i]);
  Serial.println();
}

void printHelp() {
  Serial.println(
      "commands:\n"
      "  status                      show settings and link state\n"
      "  link usb|wifi               drive over this cable (drive.py --badge) or over Wi-Fi\n"
      "  wifi <ssid> [password]      join a network (quote SSIDs with spaces)\n"
      "  scan                        list 2.4 GHz networks the badge can see\n"
      "  url ws://<ip>:8793/         where drive.py listens (--host 0.0.0.0)\n"
      "  token <secret>              the secret drive.py was started with (--token)\n"
      "  lcd invert <0|1>            fix inverted colours (applies after reboot)\n"
      "  lcd flip                    rotate the screen 180 degrees (applies after reboot)\n"
      "  buttons                     toggle printing raw shift-register bytes\n"
      "  shot                        dump the screen as hex (tools/badge_shot.py)\n"
      "  datapin <gpio>              74HC165 QH pin (7 or 8)\n"
      "  map <A B Home Down Left Right Up Aux1>   shift position of each button\n"
      "  polarity <low|high>         level of a pressed button\n"
      "  reboot");
}

bool handle(String cmdLine) {
  const String cmd = nextToken(cmdLine);
  if (cmd.isEmpty()) return false;
  if (cmd == "help") {
    printHelp();
  } else if (cmd == "status") {
    printStatus();
  } else if (cmd == "link") {
    const String what = nextToken(cmdLine);
    if (what != "usb" && what != "wifi") {
      Serial.println("link usb | link wifi");
      return false;
    }
    current.usb = what == "usb";
    settings::save();
    Serial.println(current.usb ? "driving over usb; run: drive.py --badge <this port>"
                               : "driving over wifi");
    return true;
  } else if (cmd == "wifi") {
    current.ssid = nextToken(cmdLine);
    current.password = nextToken(cmdLine);
    settings::save();
    Serial.printf("saved wifi '%s'\n", current.ssid.c_str());
    return true;
  } else if (cmd == "scan") {
    WiFi.disconnect();  // A pending join blocks scanning; the link rejoins within 5 s.
    const int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
      Serial.printf("  %-32s ch%-2d %4d dBm %s\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i),
                    WiFi.encryptionType(i) == WIFI_AUTH_WPA2_ENTERPRISE ? "enterprise" : "");
    }
    Serial.printf("%d networks\n", n);
  } else if (cmd == "url") {
    current.url = nextToken(cmdLine);
    settings::save();
    Serial.printf("saved url '%s'\n", current.url.c_str());
    return true;
  } else if (cmd == "token") {
    current.token = nextToken(cmdLine);
    settings::save();
    Serial.println(current.token.length() ? "saved token" : "cleared token");
    return true;
  } else if (cmd == "lcd") {
    const String what = nextToken(cmdLine);
    if (what == "invert") {
      current.invertLcd = nextToken(cmdLine).toInt() != 0;
    } else if (what == "flip") {
      current.flipLcd = !current.flipLcd;
    } else {
      Serial.println("lcd invert <0|1> | lcd flip");
      return false;
    }
    settings::save();
    Serial.println("saved; reboot to apply");
  } else if (cmd == "shot") {
    shotRequested = true;
  } else if (cmd == "buttons") {
    monitor = !monitor;
    Serial.printf("button monitor %s\n", monitor ? "on (press buttons; run again to stop)" : "off");
  } else if (cmd == "datapin") {
    const int pin = nextToken(cmdLine).toInt();
    if (pin != 7 && pin != 8) {
      Serial.println("datapin must be 7 or 8 (GPIO0 is the LCD D/C line)");
      return false;
    }
    current.buttons.dataPin = pin;
    buttons::setMap(current.buttons);
    settings::save();
    Serial.printf("data pin GPIO%d\n", pin);
  } else if (cmd == "map") {
    ButtonMap next = current.buttons;
    for (uint8_t i = 0; i < 8; i++) {
      const String t = nextToken(cmdLine);
      if (t.isEmpty() || t.toInt() < 0 || t.toInt() > 7) {
        Serial.println("map needs eight positions 0-7");
        return false;
      }
      next.bitOf[i] = t.toInt();
    }
    current.buttons = next;
    buttons::setMap(next);
    settings::save();
    printStatus();
  } else if (cmd == "polarity") {
    current.buttons.activeHigh = nextToken(cmdLine) == "high";
    buttons::setMap(current.buttons);
    settings::save();
    printStatus();
  } else if (cmd == "reboot") {
    ESP.restart();
  } else {
    Serial.printf("unknown command '%s'; try help\n", cmd.c_str());
  }
  return false;
}

}  // namespace

namespace settings {

Settings &get() { return current; }

void load() {
  prefs.begin(NS, true);
  current.ssid = prefs.getString("ssid", "");
  current.password = prefs.getString("pass", "");
  current.url = prefs.getString("url", "");
  current.token = prefs.getString("token", "");
  current.usb = prefs.getBool("usb", false);
  current.invertLcd = prefs.getBool("invert", true);
  current.flipLcd = prefs.getBool("flip", false);
  current.buttons = {board::SR_DATA_DEFAULT, {0, 1, 2, 3, 4, 5, 6, 7}, false};
  current.buttons.dataPin = prefs.getInt("data", board::SR_DATA_DEFAULT);
  current.buttons.activeHigh = prefs.getBool("high", false);
  prefs.getBytes("map", current.buttons.bitOf, sizeof(current.buttons.bitOf));
  prefs.end();
}

void save() {
  prefs.begin(NS, false);
  prefs.putString("ssid", current.ssid);
  prefs.putString("pass", current.password);
  prefs.putString("url", current.url);
  prefs.putString("token", current.token);
  prefs.putBool("usb", current.usb);
  prefs.putBool("invert", current.invertLcd);
  prefs.putBool("flip", current.flipLcd);
  prefs.putInt("data", current.buttons.dataPin);
  prefs.putBool("high", current.buttons.activeHigh);
  prefs.putBytes("map", current.buttons.bitOf, sizeof(current.buttons.bitOf));
  prefs.end();
}

bool pollConsole() {
  bool changed = false;
  while (Serial.available()) {
    const char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (line.startsWith("{")) {
        // drive.py telemetry on the USB transport; never echoed, it arrives at 20 Hz.
        robotlink::feedTelemetry(line);
      } else if (line.length()) {
        Serial.printf("> %s\n", line.c_str());
        changed |= handle(line);
      }
      line = "";
    } else if (line.length() < 1024) {  // drive.py's telemetry line is longer than a command.
      line += c;
    }
  }
  return changed;
}

bool monitoringButtons() { return monitor; }

bool takeShotRequest() {
  const bool requested = shotRequested;
  shotRequested = false;
  return requested;
}

}  // namespace settings
