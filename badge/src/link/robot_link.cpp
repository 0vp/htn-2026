#include "robot_link.h"

#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <freertos/semphr.h>
#include <string.h>
#include <sys/time.h>

#include "settings.h"

namespace {

constexpr uint32_t RECONNECT_MS = 1500;
/**
 * The core's auto-reconnect backs off to ~90 s after an AP vanishes (e.g. robot reboot), and
 * WiFi.reconnect() doesn't recover it either, so retry with a fresh join.
 */
constexpr uint32_t WIFI_RETRY_MS = 5000;
/**
 * After the robot reboots, the badge can stay "associated" with an AP that no longer knows it,
 * so the socket never reopens. If it stays down this long with Wi-Fi up, rejoin from scratch.
 */
constexpr uint32_t SOCKET_DOWN_REJOIN_MS = 6000;
/** Larger frames (LiDAR point batches) are skipped: they don't fit the C3's heap budget. */
constexpr size_t MAX_MESSAGE = 4096;
/**
 * The robot sends telemetry at 5 Hz, which doubles as a heartbeat. ESP32 TCP writes to a dead
 * peer block for up to 10 s once the send buffer fills, freezing the badge, so stop writing
 * soon after the robot goes quiet and then drop the connection.
 */
constexpr uint32_t QUIET_STOP_SENDING_MS = 600;
constexpr uint32_t QUIET_CLOSE_MS = 1500;
constexpr size_t PACKET_MAX = 320;

/** Exposes the library's close-without-writing, so dropping a dead link can't block. */
class RobotSocket : public WebSocketsClient {
 public:
  void drop() { clientDisconnect(&_client); }
};

struct Target {
  String host;
  uint16_t port = 80;
  String path = "/";
  bool valid = false;
};

RobotSocket socket;
Target target;
String ssid, password;
bool wifiStarted = false;
bool socketStarted = false;
bool socketOpen = false;
bool timeRequested = false;
uint32_t wifiLostSince = 0;
uint32_t socketDownSince = 0;
uint32_t sent = 0, received = 0;
uint32_t lastReceiveMs = 0;
Telemetry latest;

// Handoff between the UI loop and the network task.
portMUX_TYPE packetLock = portMUX_INITIALIZER_UNLOCKED;
char packet[PACKET_MAX];
size_t packetLength = 0;
SemaphoreHandle_t settingsLock = nullptr;
String pendingSsid, pendingPassword, pendingUrl;
bool pendingConfig = false;

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
  if (doc["control"].is<JsonObjectConst>()) {
    strlcpy(latest.owner, doc["control"]["owner"] | "none", sizeof latest.owner);
    latest.supervised = doc["control"]["supervised"] | false;
    latest.robotEstop = doc["control"]["estop"] | false;
  }
  readFloat(doc["duty"]["left"], latest.dutyLeft);
  readFloat(doc["duty"]["right"], latest.dutyRight);
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
  filter["control"] = true;
  filter["duty"] = true;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length, DeserializationOption::Filter(filter)) == DeserializationError::Ok) {
    merge(doc);
  }
}

void onEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      socketOpen = true;
      lastReceiveMs = millis();
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
  if (socketStarted) socket.drop();
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

/** Applies new settings; runs on the network task. */
void applyConfig() {
  xSemaphoreTake(settingsLock, portMAX_DELAY);
  const String newSsid = pendingSsid, newPassword = pendingPassword, url = pendingUrl;
  pendingConfig = false;
  xSemaphoreGive(settingsLock);

  stopSocket();
  target = parseUrl(url);
  if (url.length() && !target.valid) Serial.println("url must look like ws://host:port/path");
  if (newSsid != ssid || newPassword != password || !wifiStarted) {
    if (wifiStarted) WiFi.disconnect(true);
    wifiStarted = false;
    ssid = newSsid;
    password = newPassword;
    startWifi();
  }
}

void rejoin() {
  WiFi.disconnect();
  WiFi.begin(ssid.c_str(), password.length() ? password.c_str() : nullptr);
}

void sendPending() {
  char out[PACKET_MAX];
  portENTER_CRITICAL(&packetLock);
  const size_t n = packetLength;
  memcpy(out, packet, n);
  packetLength = 0;
  portEXIT_CRITICAL(&packetLock);
  if (!n || !socketOpen || millis() - lastReceiveMs > QUIET_STOP_SENDING_MS) return;
  if (socket.sendTXT(out, n)) sent++;
}

void networkStep() {
  if (pendingConfig) applyConfig();
  if (!wifiStarted) return;
  if (WiFi.status() != WL_CONNECTED) {
    if (socketStarted) stopSocket();
    const uint32_t now = millis();
    if (!wifiLostSince) wifiLostSince = now;
    if (now - wifiLostSince >= WIFI_RETRY_MS) {
      wifiLostSince = now;
      rejoin();
    }
    return;
  }
  wifiLostSince = 0;
  if (!timeRequested) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    timeRequested = true;
  }
  startSocket();
  if (socketStarted) socket.loop();
  sendPending();

  const uint32_t now = millis();
  if (socketOpen && now - lastReceiveMs > QUIET_CLOSE_MS) {
    Serial.println("robot went quiet; dropping link");
    socket.drop();
    socketOpen = false;
  }
  if (socketOpen) {
    socketDownSince = 0;
  } else if (!socketDownSince) {
    socketDownSince = now;
  } else if (now - socketDownSince >= SOCKET_DOWN_REJOIN_MS) {
    Serial.println("robot unreachable; rejoining wifi");
    socketDownSince = 0;
    stopSocket();
    rejoin();
  }
}

/**
 * Wi-Fi and socket calls can block for seconds when the robot vanishes, so they live on their
 * own task and the screen and buttons keep running.
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
  pendingConfig = true;
  xSemaphoreGive(settingsLock);
}

bool send(const char *json, size_t length) {
  if (length > PACKET_MAX) return false;
  portENTER_CRITICAL(&packetLock);
  memcpy(packet, json, length);
  packetLength = length;
  portEXIT_CRITICAL(&packetLock);
  return true;
}

Status status() {
  if (ssid.isEmpty() || !target.valid) return Status::Unconfigured;
  if (WiFi.status() != WL_CONNECTED) return Status::JoiningWifi;
  if (!socketOpen) return Status::Connecting;
  return isOpen() ? Status::Open : Status::Silent;
}

const char *statusText() {
  switch (status()) {
    case Status::Unconfigured:
      return ssid.isEmpty() ? "no wifi set" : "no robot url";
    case Status::JoiningWifi:
      return "joining wifi";
    case Status::Connecting:
      return "connecting";
    case Status::Silent:
      return "robot silent";
    default:
      return "online";
  }
}

bool isOpen() { return socketOpen && millis() - lastReceiveMs <= QUIET_STOP_SENDING_MS; }
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
