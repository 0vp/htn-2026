#include "server.h"

#include <ArduinoJson.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <esp_system.h>
#include <freertos/semphr.h>

#include "../control/steering.h"
#include "../hal/motor.h"
#include "settings.h"

namespace {

constexpr uint16_t CONTROL_PORT = 81;
constexpr uint32_t TELEMETRY_MS = 50;  // 20 Hz, matching robot/steering
constexpr uint32_t WIFI_RETRY_MS = 5000;
/**
 * Writes to a dead client block for up to 10 s once the send buffer fills, so only send to
 * clients heard from recently and drop silent ones (badge/README.md).
 */
constexpr uint32_t QUIET_SKIP_MS = 1000;
constexpr uint32_t QUIET_DROP_MS = 2500;

/** Exposes the library's close-without-writing, so dropping a dead client can't block. */
class ControlServer : public WebSocketsServer {
 public:
  using WebSocketsServer::WebSocketsServer;
  void drop(uint8_t num) { clientDisconnect(&_clients[num]); }
};

ControlServer socket(CONTROL_PORT);
SteeringControl control;
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;

bool localActive = false;
float localDuty = 0, localSteering = 0;

String ssid, password, token;
bool wifiStarted = false;
bool serverStarted = false;
uint32_t wifiLostSince = 0;
uint32_t lastTelemetry = 0;
uint32_t lastCommandMs = 0;
uint32_t commands = 0;
uint8_t clients = 0;
uint32_t lastHeard[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
bool connectedClient[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
bool rejected[WEBSOCKETS_SERVER_CLIENT_MAX] = {};

SemaphoreHandle_t settingsLock = nullptr;
String pendingSsid, pendingPassword, pendingToken;
bool pendingConfig = false;

/** Mirrors robot/steering/src/protocol.h; `supervise` messages from the network are refused. */
void handlePacket(const uint8_t *payload, size_t length) {
  JsonDocument doc;
  if (length > 512 || deserializeJson(doc, payload, length)) {
    portENTER_CRITICAL(&lock);
    control.stop();
    portEXIT_CRITICAL(&lock);
    return;
  }
  const char *type = doc["type"] | "";
  portENTER_CRITICAL(&lock);
  if (strcmp(type, "supervise") == 0 || strcmp(type, "command") != 0) {
    control.stop();  // Supervision is granted at the badge, never over the network.
  } else if (doc["estop"] | true) {
    control.command(false, true, 0, 0, millis());
  } else {
    const bool armed = doc["armed"] == true;
    if (armed && (!doc["drive"]["duty"].is<float>() || !doc["drive"]["steering_deg"].is<float>())) {
      control.stop();
    } else {
      control.command(armed, false, doc["drive"]["duty"] | 0.0f, doc["drive"]["steering_deg"] | 0.0f,
                      millis());
    }
  }
  portEXIT_CRITICAL(&lock);
  lastCommandMs = millis();
  commands++;
}

bool tokenAccepted(const uint8_t *path, size_t length) {
  if (token.isEmpty()) return false;
  const String url(reinterpret_cast<const char *>(path), length);
  return url.indexOf("token=" + token) >= 0;
}

void onEvent(uint8_t client, WStype_t type, uint8_t *payload, size_t length) {
  if (client >= WEBSOCKETS_SERVER_CLIENT_MAX) return;
  lastHeard[client] = millis();
  switch (type) {
    case WStype_CONNECTED:
      clients++;
      connectedClient[client] = true;
      rejected[client] = !tokenAccepted(payload, length);
      Serial.printf("client %u connected from %s%s\n", client,
                    socket.remoteIP(client).toString().c_str(),
                    rejected[client] ? " (rejected: missing or wrong token)" : "");
      break;
    case WStype_DISCONNECTED:
      if (connectedClient[client] && clients) clients--;
      connectedClient[client] = false;
      Serial.printf("client %u disconnected\n", client);
      portENTER_CRITICAL(&lock);
      control.stop();
      portEXIT_CRITICAL(&lock);
      break;
    case WStype_TEXT:
      if (!rejected[client]) handlePacket(payload, length);
      break;
    default:
      break;
  }
}

String telemetryJson() {
  portENTER_CRITICAL(&lock);
  const SteeringControl state = control;
  const bool human = localActive;
  portEXIT_CRITICAL(&lock);

  JsonDocument doc;
  doc["type"] = "telemetry";
  doc["drivetrain"] = "single_steer_v1";
  doc["transport"] = "wifi_ws_badge";
  doc["uptime_ms"] = millis();
  doc["reset_reason"] = int(esp_reset_reason());
  doc["motor_duty"] = motor::appliedDuty();
  doc["steering_deg"] = motor::appliedSteering();
  doc["steering_feedback"] = "commanded_servo_pulse_not_measured_angle";
  doc["odometry_calibrated"] = false;
  doc["encoder_ticks"] = nullptr;  // The badge has no free pins for the encoder.
  doc["control"]["supervised"] = state.supervised;
  doc["control"]["estop"] = state.estop;
  doc["control"]["owner"] = human ? "human" : (state.active ? "agent" : "none");
  doc["capabilities"]["drive_base"] = true;
  doc["capabilities"]["set_arm"] = false;
  doc["capabilities"]["run_winch"] = false;
  String out;
  serializeJson(doc, out);
  return out;
}

void broadcast() {
  const String state = telemetryJson();
  for (uint8_t i = 0; i < WEBSOCKETS_SERVER_CLIENT_MAX; i++) {
    if (connectedClient[i] && !rejected[i] && millis() - lastHeard[i] <= QUIET_SKIP_MS) {
      socket.sendTXT(i, state.c_str(), state.length());
    }
  }
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
  token = pendingToken;
  pendingConfig = false;
  xSemaphoreGive(settingsLock);
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
  if (!serverStarted) {
    // Starting the listener before Wi-Fi brings up lwIP asserts on an invalid mbox.
    serverStarted = true;
    socket.begin();
    socket.onEvent(onEvent);
    Serial.printf("control server on ws://%s:%u/?token=...\n", WiFi.localIP().toString().c_str(),
                  CONTROL_PORT);
  }
  socket.loop();

  const uint32_t now = millis();
  for (uint8_t i = 0; i < WEBSOCKETS_SERVER_CLIENT_MAX; i++) {
    const bool silent = now - lastHeard[i] > QUIET_DROP_MS;
    if (connectedClient[i] && (silent || rejected[i])) {
      Serial.printf("client %u %s; dropping\n", i, rejected[i] ? "rejected" : "silent");
      rejected[i] = false;
      socket.drop(i);
    }
  }
  if (now - lastTelemetry >= TELEMETRY_MS) {
    lastTelemetry = now;
    broadcast();
  }
}

/**
 * Wi-Fi and socket calls can block for seconds when a peer vanishes, so they live on their own
 * task: the screen, the buttons and the motor watchdog keep running.
 */
void networkTask(void *) {
  for (;;) {
    networkStep();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

}  // namespace

namespace robotserver {

void begin(const Settings &settings) {
  settingsLock = xSemaphoreCreateMutex();
  reconfigure(settings);
  xTaskCreate(networkTask, "robotserver", 6144, nullptr, 1, nullptr);
}

void reconfigure(const Settings &settings) {
  xSemaphoreTake(settingsLock, portMAX_DELAY);
  pendingSsid = settings.ssid;
  pendingPassword = settings.password;
  pendingToken = settings.token;
  pendingConfig = true;
  xSemaphoreGive(settingsLock);
}

Status status() {
  if (ssid.isEmpty() || token.isEmpty()) return Status::Unconfigured;
  if (WiFi.status() != WL_CONNECTED) return Status::JoiningWifi;
  return Status::Ready;
}

const char *statusText() {
  switch (status()) {
    case Status::Unconfigured:
      return ssid.isEmpty() ? "no wifi set" : "no token set";
    case Status::JoiningWifi:
      return "joining wifi";
    default:
      return clients ? "agent connected" : "waiting for agent";
  }
}

String localIp() { return WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String("-"); }
int wifiRssi() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }
uint8_t clientCount() { return clients; }
uint32_t agentSilenceMs() { return commands ? millis() - lastCommandMs : UINT32_MAX; }

bool snapshot(float &duty, float &steering) {
  portENTER_CRITICAL(&lock);
  control.tick(millis());
  bool moving = false;
  if (localActive && !control.estop) {
    duty = localDuty;
    steering = localSteering;
    moving = true;
  } else if (control.active) {
    duty = control.duty;
    steering = control.steering;
    moving = true;
  } else {
    // Drive cuts at once; the servo holds its last angle, as robot/steering does.
    duty = 0;
    steering = localSteering != 0 ? localSteering : control.steering;
  }
  portEXIT_CRITICAL(&lock);
  return moving;
}

void supervise(bool enabled) {
  portENTER_CRITICAL(&lock);
  control.supervise(enabled);
  portEXIT_CRITICAL(&lock);
}

void emergencyStop() {
  portENTER_CRITICAL(&lock);
  const bool latched = control.estop;
  control.command(false, true, 0, 0, millis());
  localActive = false;
  portEXIT_CRITICAL(&lock);
  if (!latched) Serial.println("E-STOP latched at the badge");
}

void clearEstop() {
  portENTER_CRITICAL(&lock);
  control.estop = false;
  portEXIT_CRITICAL(&lock);
}

void setLocal(bool active, float duty, float steering) {
  portENTER_CRITICAL(&lock);
  localActive = active && !control.estop;
  localDuty = localActive ? duty : 0;
  localSteering = steering;
  if (localActive) control.stop();  // A hand on the D-pad outranks the agent.
  portEXIT_CRITICAL(&lock);
}

bool estopLatched() { return control.estop; }
bool supervised() { return control.supervised; }

const char *owner() {
  portENTER_CRITICAL(&lock);
  const bool human = localActive;
  const bool agent = control.active;
  portEXIT_CRITICAL(&lock);
  return human ? "human" : (agent ? "agent" : "none");
}

}  // namespace robotserver
