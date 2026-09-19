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

WebSocketsServer socket(config::CONTROL_PORT);
Command latest;
uint8_t owner = NO_OWNER;
uint32_t ownerLastMs = 0;
bool latched = true;  // boot in E-STOP: an operator must arm deliberately
uint8_t clients = 0;
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
  switch (type) {
    case WStype_CONNECTED:
      clients++;
      Serial.printf("client %u connected from %s\n", client, socket.remoteIP(client).toString().c_str());
      break;
    case WStype_DISCONNECTED:
      if (clients) clients--;
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
  if (clients) socket.broadcastTXT(json, length);
}

}  // namespace server
