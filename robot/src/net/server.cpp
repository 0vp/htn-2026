#include "server.h"

#include <WebSocketsServer.h>
#include <WiFi.h>

#include "../config.h"
#include "authority.h"

#if __has_include("../secrets.h")
#include "../secrets.h"
#else
#error "Copy src/secrets.example.h to src/secrets.h and set ROBOT_AP_PASSWORD"
#endif

namespace {

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
uint8_t clients = 0;
uint32_t lastHeard[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
bool connectedClient[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
bool localClient[WEBSOCKETS_SERVER_CLIENT_MAX] = {};

/** Clients on the robot's own access point (192.168.4.x) already proved the WPA2 password. */
bool onAccessPoint(const IPAddress &ip) {
  const IPAddress ap = WiFi.softAPIP();
  return ip[0] == ap[0] && ip[1] == ap[1] && ip[2] == ap[2];
}

void onEvent(uint8_t client, WStype_t type, uint8_t *payload, size_t length) {
  if (client >= WEBSOCKETS_SERVER_CLIENT_MAX) return;
  lastHeard[client] = millis();
  switch (type) {
    case WStype_CONNECTED: {
      const IPAddress ip = socket.remoteIP(client);
      clients++;
      connectedClient[client] = true;
      localClient[client] = onAccessPoint(ip);
      Serial.printf("client %u connected from %s\n", client, ip.toString().c_str());
      break;
    }
    case WStype_DISCONNECTED:
      if (connectedClient[client] && clients) clients--;
      connectedClient[client] = false;
      Serial.printf("client %u disconnected\n", client);
      authority::onDisconnect(client);
      break;
    case WStype_TEXT: {
      Command c;
      if (parseCommand(payload, length, c)) authority::onCommand(client, localClient[client], c);
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
  authority::tick();

}

bool snapshot(Command &out) { return authority::snapshot(out); }
bool estopLatched() { return authority::status().latched; }
uint8_t clientCount() { return clients; }

void broadcast(const char *json, size_t length) {
  for (uint8_t i = 0; i < WEBSOCKETS_SERVER_CLIENT_MAX; i++) {
    if (connectedClient[i] && millis() - lastHeard[i] <= QUIET_SKIP_MS) {
      socket.sendTXT(i, json, length);
    }
  }
}

}  // namespace server
