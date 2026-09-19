#include "network.h"
#include <WiFi.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include "../runtime.h"

namespace network {
namespace {
Preferences store;
String secret, apName;
String pendingSsid, pendingPassword;
bool pending = false;
}
String password() { return secret; }
void configure(const String& ssid, const String& passphrase) {
  wirelessSupervision(false);
  pendingSsid = ssid; pendingPassword = passphrase; pending = true;
}
void printSetup() {
  Serial.printf("WIFI_SETUP ssid=%s password=%s url=http://192.168.4.1 user=robot\n", apName.c_str(), secret.c_str());
}
void begin() {
  store.begin("steering-wifi", false);
  secret = store.getString("ap-key", "");
  if (secret.length() != 16) {
    char key[17]; snprintf(key, sizeof(key), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
    secret = key; store.putString("ap-key", secret);
  }
  char name[32]; snprintf(name, sizeof(name), "HTN-Robot-%04X", unsigned(ESP.getEfuseMac() & 0xffff));
  apName = name;
  WiFi.persistent(false);
  WiFi.setHostname("htn-robot");
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.softAP(apName.c_str(), secret.c_str());
  String ssid = store.getString("ssid", "");
  if (ssid.length()) WiFi.begin(ssid.c_str(), store.getString("pass", "").c_str());
  MDNS.begin("htn-robot");
  MDNS.addService("http", "tcp", 80);
  MDNS.addService("ws", "tcp", 81);
  webBegin(); transportBegin();
  // Printed locally for initial pairing; never commit this generated credential.
  printSetup();
}
void poll() {
  webPoll(); transportPoll();
  if (pending) {
    pending = false;
    store.putString("ssid", pendingSsid); store.putString("pass", pendingPassword);
    WiFi.begin(pendingSsid.c_str(), pendingPassword.c_str());
    pendingPassword = "";
  }
}
void describe(JsonDocument& doc) {
  doc["network"]["ap_ssid"] = apName;
  doc["network"]["ap_ip"] = WiFi.softAPIP().toString();
  doc["network"]["station_connected"] = WiFi.status() == WL_CONNECTED;
  doc["network"]["station_ip"] = WiFi.localIP().toString();
  doc["network"]["hostname"] = "htn-robot.local";
  doc["network"]["controller_connected"] = hasController();
}
}
