#include "robot_link.h"

#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <sys/time.h>

#include "settings.h"

namespace {

constexpr uint32_t RECONNECT_MS = 1500;
/** Larger frames (LiDAR point batches) are skipped: they don't fit the C3's heap budget. */
constexpr size_t MAX_MESSAGE = 4096;

struct Target {
  String host;
  uint16_t port = 80;
  String path = "/";
  bool valid = false;
};

WebSocketsClient socket;
Target target;
String ssid, password;
bool wifiStarted = false;
bool socketStarted = false;
bool socketOpen = false;
bool timeRequested = false;
uint32_t sent = 0, received = 0;
uint32_t lastReceiveMs = 0;
Telemetry latest;

Target parseUrl(const String &url) {
  Target t;
  if (!url.startsWith("ws://")) return t;  // wss:// needs TLS, which this firmware leaves out.
  String rest = url.substring(5);
  const int slash = rest.indexOf('/');
  if (slash >= 0) {
    t.path = rest.substring(slash);
    rest = rest.substring(0, slash);
  }
  const int colon = rest.indexOf(':');
  if (colon >= 0) {
    t.port = rest.substring(colon + 1).toInt();
    rest = rest.substring(0, colon);
  }
  t.host = rest;
  t.valid = t.host.length() > 0 && t.port > 0;
  return t;
}

void readFloat(JsonVariantConst v, float &out) {
  if (v.is<float>()) out = v.as<float>();
}

void merge(JsonDocument &doc) {
  readFloat(doc["packVolts"], latest.packVolts);
  readFloat(doc["rpm"]["left"], latest.rpmLeft);
  readFloat(doc["rpm"]["right"], latest.rpmRight);
  if (doc["rssi"].is<int>()) latest.robotRssi = doc["rssi"];
  for (int i = 0; i < 3; i++) {
    readFloat(doc["winchPos"][i], latest.winchPos[i]);
    if (doc["limits"][i].is<JsonArrayConst>()) {
      latest.limits[i][0] = doc["limits"][i][0] | false;
      latest.limits[i][1] = doc["limits"][i][1] | false;
    }
  }
  // Pose arrives as [x, y, z, yaw] on "pose" or "points" messages.
  JsonArrayConst pose = doc["pose"];
  if (pose.size() >= 3) {
    latest.hasPose = true;
    latest.poseX = pose[0] | 0.0f;
    latest.poseZ = pose[2] | 0.0f;
    latest.poseYaw = pose[3] | 0.0f;
  }
  latest.updatedMs = millis();
}

void onMessage(const uint8_t *payload, size_t length) {
  received++;
  lastReceiveMs = millis();
  if (length > MAX_MESSAGE) return;
  JsonDocument filter;
  filter["packVolts"] = true;
  filter["rpm"] = true;
  filter["rssi"] = true;
  filter["winchPos"] = true;
  filter["limits"] = true;
  filter["pose"] = true;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length, DeserializationOption::Filter(filter)) == DeserializationError::Ok) {
    merge(doc);
  }
}

void onEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      socketOpen = true;
      Serial.printf("robot link open: %s:%u%s\n", target.host.c_str(), target.port, target.path.c_str());
      break;
    case WStype_DISCONNECTED:
      if (socketOpen) Serial.println("robot link closed");
      socketOpen = false;
      break;
    case WStype_TEXT:
      onMessage(payload, length);
      break;
    default:
      break;
  }
}

/** ESP32 Arduino doesn't resolve *.local through DNS, so ask mDNS directly. */
String resolve(const String &host) {
  if (!host.endsWith(".local")) return host;
  const IPAddress ip = MDNS.queryHost(host.substring(0, host.length() - 6), 2000);
  return ip == IPAddress() ? host : ip.toString();
}

void startSocket() {
  if (!target.valid || socketStarted) return;
  const String host = resolve(target.host);
  socket.begin(host, target.port, target.path);
  socket.onEvent(onEvent);
  socket.setReconnectInterval(RECONNECT_MS);
  socketStarted = true;
}

void stopSocket() {
  if (socketStarted) socket.disconnect();
  socketStarted = false;
  socketOpen = false;
}

void startWifi() {
  if (ssid.isEmpty()) return;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // Power save adds 100 ms+ of latency to every packet.
  WiFi.setAutoReconnect(true);
  // Venue networks have many APs; scan every channel and join the strongest, not the first.
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  WiFi.begin(ssid.c_str(), password.length() ? password.c_str() : nullptr);
  MDNS.begin("robot-badge");
  wifiStarted = true;
}

}  // namespace

namespace robotlink {

void begin(const Settings &settings) { reconfigure(settings); }

void reconfigure(const Settings &settings) {
  stopSocket();
  target = parseUrl(settings.url);
  if (settings.url.length() && !target.valid) Serial.println("url must look like ws://host:port/path");
  if (settings.ssid != ssid || settings.password != password || !wifiStarted) {
    if (wifiStarted) WiFi.disconnect(true);
    wifiStarted = false;
    ssid = settings.ssid;
    password = settings.password;
    startWifi();
  }
}

void loop() {
  if (!wifiStarted) return;
  if (WiFi.status() != WL_CONNECTED) {
    if (socketStarted) stopSocket();
    return;
  }
  if (!timeRequested) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    timeRequested = true;
  }
  startSocket();
  if (socketStarted) socket.loop();
}

bool send(const char *json, size_t length) {
  if (!socketOpen) return false;
  const bool ok = socket.sendTXT(json, length);
  if (ok) sent++;
  return ok;
}

Status status() {
  if (ssid.isEmpty() || !target.valid) return Status::Unconfigured;
  if (WiFi.status() != WL_CONNECTED) return Status::JoiningWifi;
  return socketOpen ? Status::Open : Status::Connecting;
}

const char *statusText() {
  switch (status()) {
    case Status::Unconfigured:
      return ssid.isEmpty() ? "no wifi set" : "no robot url";
    case Status::JoiningWifi:
      return "joining wifi";
    case Status::Connecting:
      return "connecting";
    default:
      return "online";
  }
}

bool isOpen() { return socketOpen; }
String localIp() { return WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String("-"); }
int wifiRssi() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }
uint32_t sentCount() { return sent; }
uint32_t receivedCount() { return received; }
uint32_t silenceMs() { return received ? millis() - lastReceiveMs : UINT32_MAX; }
const Telemetry &telemetry() { return latest; }

uint64_t timestampMs() {
  timeval now;
  gettimeofday(&now, nullptr);
  if (now.tv_sec < 1700000000) return millis();
  return static_cast<uint64_t>(now.tv_sec) * 1000 + now.tv_usec / 1000;
}

}  // namespace robotlink
