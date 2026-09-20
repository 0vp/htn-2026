#include "client.h"

#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <freertos/semphr.h>

#include "settings.h"

namespace {

constexpr uint32_t COMMAND_MS = 50;  // 20 Hz; drive.py drops an app command after 500 ms.
constexpr uint32_t WIFI_RETRY_MS = 5000;
constexpr uint32_t REDIAL_MS = 2000;
constexpr uint8_t FLUSH_PACKETS = 5;  // Repeats of an armed/estop/silent change, against loss.

WebSocketsClient socket;
robotlink::Telemetry state;
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;

struct Intent {
  bool armed = false;
  bool estop = false;
  bool silent = true;
  float linear = 0;
  float angular = 0;
};

Intent intent;
uint8_t flush = 0;
uint32_t sequence = 0;

String ssid, password, host, path;
uint16_t port = 8793;
bool wifiStarted = false;
bool dialled = false;
bool connected = false;
uint32_t wifiLostSince = 0;
uint32_t lastCommand = 0;
uint32_t lastTelemetry = 0;

SemaphoreHandle_t settingsLock = nullptr;
String pendingSsid, pendingPassword, pendingUrl, pendingToken;
bool pendingConfig = false;

/** Splits `ws://host[:port][/path][?query]` and appends `token` when the URL carries none. */
bool parseUrl(const String &url, const String &token, String &outHost, uint16_t &outPort,
              String &outPath) {
  if (!url.startsWith("ws://")) return false;  // wss would need TLS on the C3; drive.py serves ws.
  const String rest = url.substring(5);
  const int slash = rest.indexOf('/');
  const String authority = slash < 0 ? rest : rest.substring(0, slash);
  outPath = slash < 0 ? "/" : rest.substring(slash);
  const int colon = authority.indexOf(':');
  outHost = colon < 0 ? authority : authority.substring(0, colon);
  outPort = colon < 0 ? 80 : authority.substring(colon + 1).toInt();
  if (outHost.isEmpty() || outPort == 0) return false;
  if (outPath.indexOf("token=") < 0 && token.length()) {
    outPath += (outPath.indexOf('?') < 0 ? "?token=" : "&token=") + token;
  }
  return true;
}

void readTelemetry(const uint8_t *payload, size_t length) {
  JsonDocument doc;
  if (length > 2048 || deserializeJson(doc, payload, length)) return;
  robotlink::Telemetry next;
  next.valid = true;
  next.at = millis();
  next.left = doc["motors"]["left"] | 0.0f;
  next.right = doc["motors"]["right"] | 0.0f;
  next.estop = doc["control"]["estop"] | doc["estop"] | true;
  next.supervised = doc["control"]["supervised"] | false;
  next.trimLeft = doc["calibration"]["left_gain"] | 1.0f;
  next.trimRight = doc["calibration"]["right_gain"] | 1.0f;
  strlcpy(next.source, doc["source"] | "", sizeof next.source);
  strlcpy(next.owner, doc["control"]["owner"] | "", sizeof next.owner);
  portENTER_CRITICAL(&lock);
  state = next;
  portEXIT_CRITICAL(&lock);
  lastTelemetry = next.at;
}

void onEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      connected = true;
      flush = FLUSH_PACKETS;  // Re-announce the current arm state to a fresh drive.py.
      Serial.printf("linked to ws://%s:%u%s\n", host.c_str(), port, path.c_str());
      break;
    case WStype_DISCONNECTED:
      if (connected) Serial.println("link lost; drive.py stops the base on its own");
      connected = false;
      portENTER_CRITICAL(&lock);
      state.valid = false;
      portEXIT_CRITICAL(&lock);
      break;
    case WStype_TEXT:
      readTelemetry(payload, length);
      break;
    default:
      break;
  }
}

/** drive.py -> wheels(): explicit armed/estop booleans, then linear/angular in -1..1. */
void sendCommand() {
  portENTER_CRITICAL(&lock);
  const Intent now = intent;
  const bool forced = flush > 0;
  if (flush) flush--;
  portEXIT_CRITICAL(&lock);
  if (now.silent && !forced) return;

  JsonDocument doc;
  doc["type"] = "command";
  doc["seq"] = ++sequence;
  doc["t"] = millis();
  doc["source"] = "badge";
  doc["armed"] = now.armed && !now.silent;
  doc["estop"] = now.estop;
  if (now.armed && !now.silent) {
    doc["drive"]["linear"] = now.linear;
    doc["drive"]["angular"] = now.angular;
  }
  String out;
  serializeJson(doc, out);
  socket.sendTXT(out);
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
  wifiStarted = true;
}

void applyConfig() {
  xSemaphoreTake(settingsLock, portMAX_DELAY);
  const String newSsid = pendingSsid, newPassword = pendingPassword;
  const String url = pendingUrl, token = pendingToken;
  pendingConfig = false;
  xSemaphoreGive(settingsLock);

  String newHost, newPath;
  uint16_t newPort = 0;
  if (url.length() && !parseUrl(url, token, newHost, newPort, newPath)) {
    Serial.println("url must look like ws://<laptop-ip>:8793/  (wss is not supported)");
  }
  if (newHost != host || newPort != port || newPath != path) {
    if (dialled) socket.disconnect();
    dialled = false;
    connected = false;
    host = newHost;
    port = newPort;
    path = newPath;
  }
  if (newSsid == ssid && newPassword == password && wifiStarted) return;
  if (wifiStarted) WiFi.disconnect(true);
  wifiStarted = false;
  ssid = newSsid;
  password = newPassword;
  startWifi();
}

void networkStep() {
  if (pendingConfig) applyConfig();
  if (!wifiStarted) return;
  if (WiFi.status() != WL_CONNECTED) {
    const uint32_t now = millis();
    if (!wifiLostSince) wifiLostSince = now;
    if (now - wifiLostSince >= WIFI_RETRY_MS) {
      // The core's auto-reconnect backs off after an AP vanishes; rejoin from scratch.
      wifiLostSince = now;
      WiFi.disconnect();
      WiFi.begin(ssid.c_str(), password.length() ? password.c_str() : nullptr);
    }
    return;
  }
  wifiLostSince = 0;
  if (!dialled) {
    if (host.isEmpty()) return;
    // Dialling before lwIP is up asserts on an invalid mbox, so wait for the station first.
    dialled = true;
    socket.onEvent(onEvent);
    socket.setReconnectInterval(REDIAL_MS);
    socket.begin(host.c_str(), port, path.c_str());
    Serial.printf("dialling ws://%s:%u%s\n", host.c_str(), port, path.c_str());
  }
  socket.loop();
  const uint32_t now = millis();
  if (connected && now - lastCommand >= COMMAND_MS) {
    lastCommand = now;
    sendCommand();
  }
}

/**
 * Wi-Fi and socket calls can block for seconds when a peer vanishes, so they live on their own
 * task: the screen and the buttons keep running.
 */
void networkTask(void *) {
  for (;;) {
    networkStep();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

}  // namespace

namespace robotlink {

void begin(const Settings &settings) {
  settingsLock = xSemaphoreCreateMutex();
  reconfigure(settings);
  xTaskCreate(networkTask, "robotlink", 6144, nullptr, 1, nullptr);
}

void reconfigure(const Settings &settings) {
  xSemaphoreTake(settingsLock, portMAX_DELAY);
  pendingSsid = settings.ssid;
  pendingPassword = settings.password;
  pendingUrl = settings.url;
  pendingToken = settings.token;
  pendingConfig = true;
  xSemaphoreGive(settingsLock);
}

Status status() {
  if (ssid.isEmpty() || host.isEmpty()) return Status::Unconfigured;
  if (WiFi.status() != WL_CONNECTED) return Status::JoiningWifi;
  return connected ? Status::Linked : Status::Dialing;
}

const char *statusText() {
  switch (status()) {
    case Status::Unconfigured:
      return ssid.isEmpty() ? "no wifi set" : "no url set";
    case Status::JoiningWifi:
      return "joining wifi";
    case Status::Dialing:
      return "dialling drive.py";
    default:
      return "linked";
  }
}

String localIp() { return WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String("-"); }
int wifiRssi() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }
bool linked() { return connected; }

void command(bool armed, bool estop, float linear, float angular, bool silent) {
  portENTER_CRITICAL(&lock);
  if (armed != intent.armed || estop != intent.estop || silent != intent.silent) {
    flush = FLUSH_PACKETS;
  }
  intent.armed = armed;
  intent.estop = estop;
  intent.silent = silent;
  intent.linear = linear;
  intent.angular = angular;
  portEXIT_CRITICAL(&lock);
}

const Telemetry &telemetry() { return state; }

uint32_t telemetrySilenceMs() { return lastTelemetry ? millis() - lastTelemetry : UINT32_MAX; }

}  // namespace robotlink
