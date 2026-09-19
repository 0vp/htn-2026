#include "server.h"

#include <WebSocketsServer.h>
#include <WiFi.h>

#include "../config.h"

#if __has_include("../secrets.h")
#include "../secrets.h"
#else
#error "Copy src/secrets.example.h to src/secrets.h and set ROBOT_AP_PASSWORD"
#endif

namespace {

constexpr uint8_t NO_OWNER = 0xFF;
/**
 * Clients send commands at 20 Hz. TCP writes to a dead client block for up to 10 s once the
 * send buffer fills, so only send to clients heard from recently and drop silent ones.
 */
constexpr uint32_t QUIET_SKIP_MS = 1000;
constexpr uint32_t QUIET_DROP_MS = 2500;

/** Exposes the library's close-without-writing, so dropping a dead client can't block. */
class ControlServer : public WebSocketsServer {
 public:
  using WebSocketsServer::WebSocketsServer;
  void drop(uint8_t num) { clientDisconnect(&_clients[num]); }
};

ControlServer socket(config::CONTROL_PORT);
Command latest;
uint8_t owner = NO_OWNER;
uint32_t ownerLastMs = 0;
bool latched = true;  // boot in E-STOP: an operator must arm deliberately
uint8_t clients = 0;
uint32_t lastHeard[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
bool connectedClient[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
// Guards owner/latest/ownerLastMs/latched between the network and actuator tasks.
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;

void release(const char *why) {
  if (owner == NO_OWNER) return;
  const uint8_t was = owner;
  portENTER_CRITICAL(&lock);
  owner = NO_OWNER;
  latest = Command();
  portEXIT_CRITICAL(&lock);
  Serial.printf("control released (client %u, %s)\n", was, why);
}

void onCommand(uint8_t client, const Command &c) {
  if (c.estop) {
    if (!latched) Serial.printf("E-STOP from client %u\n", client);
    portENTER_CRITICAL(&lock);
    latched = true;
    portEXIT_CRITICAL(&lock);
    release("e-stop");
    return;
  }
  if (!c.armed) {
    if (client == owner) release("disarmed");
    return;
  }
  // Armed and not stopped: take control if free, ignore if someone else holds it.
  if (owner == NO_OWNER) {
    owner = client;
    Serial.printf("control taken by client %u\n", client);
  }
  if (client != owner) return;
  portENTER_CRITICAL(&lock);
  latched = false;
  latest = c;
  ownerLastMs = millis();
  portEXIT_CRITICAL(&lock);
}

void onEvent(uint8_t client, WStype_t type, uint8_t *payload, size_t length) {
  if (client < WEBSOCKETS_SERVER_CLIENT_MAX) lastHeard[client] = millis();
  switch (type) {
    case WStype_CONNECTED:
      clients++;
      connectedClient[client] = true;
      Serial.printf("client %u connected from %s\n", client, socket.remoteIP(client).toString().c_str());
      break;
    case WStype_DISCONNECTED:
      if (connectedClient[client] && clients) clients--;
      connectedClient[client] = false;
      Serial.printf("client %u disconnected\n", client);
      if (client == owner) release("disconnected");
      break;
    case WStype_TEXT: {
      Command c;
      if (parseCommand(payload, length, c)) onCommand(client, c);
      break;
    }
    default:
      break;
  }
}

}  // namespace

namespace server {

void begin() {
  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  WiFi.softAP(config::AP_SSID, ROBOT_AP_PASSWORD, config::AP_CHANNEL);
  Serial.printf("access point '%s' up, control at ws://%s:%u/\n", config::AP_SSID,
                WiFi.softAPIP().toString().c_str(), config::CONTROL_PORT);
  socket.begin();
  socket.onEvent(onEvent);
}

void loop() {
  socket.loop();
  const uint32_t now = millis();
  for (uint8_t i = 0; i < WEBSOCKETS_SERVER_CLIENT_MAX; i++) {
    if (connectedClient[i] && now - lastHeard[i] > QUIET_DROP_MS) {
      Serial.printf("client %u silent; dropping\n", i);
      socket.drop(i);
    }
  }
  if (owner != NO_OWNER && millis() - ownerLastMs > config::RELEASE_OWNER_MS) release("silent");
}

bool snapshot(Command &out) {
  portENTER_CRITICAL(&lock);
  const bool fresh = owner != NO_OWNER && !latched && millis() - ownerLastMs <= config::FAILSAFE_MS;
  out = latest;
  portEXIT_CRITICAL(&lock);
  return fresh;
}
bool estopLatched() { return latched; }
uint8_t clientCount() { return clients; }

void broadcast(const char *json, size_t length) {
  const uint32_t now = millis();
  for (uint8_t i = 0; i < WEBSOCKETS_SERVER_CLIENT_MAX; i++) {
    if (connectedClient[i] && now - lastHeard[i] <= QUIET_SKIP_MS) socket.sendTXT(i, json, length);
  }
}

}  // namespace server
