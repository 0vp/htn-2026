#include "server.h"

#include <ESPmDNS.h>
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
constexpr uint32_t STA_RETRY_MS = 10000;

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
bool rejected[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
uint32_t staLostSince = 0;

/** Clients on the robot's own access point (192.168.4.x) already proved the WPA2 password. */
bool onAccessPoint(const IPAddress &ip) {
  const IPAddress ap = WiFi.softAPIP();
  return ip[0] == ap[0] && ip[1] == ap[1] && ip[2] == ap[2];
}

/** Venue-network clients must connect with ws://<ip>:81/?token=ROBOT_AGENT_TOKEN. */
bool tokenAccepted(const uint8_t *path, size_t length) {
#ifdef ROBOT_AGENT_TOKEN
  const String url(reinterpret_cast<const char *>(path), length);
  return url.indexOf("token=" ROBOT_AGENT_TOKEN) >= 0;
#else
  (void)path;
  (void)length;
  return false;
#endif
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
      rejected[client] = !localClient[client] && !tokenAccepted(payload, length);
      Serial.printf("client %u connected from %s%s\n", client, ip.toString().c_str(),
                    rejected[client] ? " (rejected: missing or wrong token)" : "");
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
      if (!rejected[client] && parseCommand(payload, length, c)) authority::onCommand(client, localClient[client], c);
      break;
    }
    default:
      break;
  }
}

void beginStation() {
#ifdef ROBOT_STA_SSID
  WiFi.begin(ROBOT_STA_SSID, ROBOT_STA_PASSWORD);
#endif
}

}  // namespace

namespace server {

void begin() {
#ifdef ROBOT_STA_SSID
  WiFi.mode(WIFI_AP_STA);
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t) {
    Serial.printf("joined %s as %s; agent at ws://%s:%u/?token=...\n", ROBOT_STA_SSID,
                  WiFi.localIP().toString().c_str(), WiFi.localIP().toString().c_str(), config::CONTROL_PORT);
  }, ARDUINO_EVENT_WIFI_STA_GOT_IP);
#else
  WiFi.mode(WIFI_AP);
#endif
  WiFi.setSleep(false);
  // With a station link the access point follows the venue network's channel.
  WiFi.softAP(config::AP_SSID, ROBOT_AP_PASSWORD, config::AP_CHANNEL);
#ifdef ROBOT_STA_SSID
  // Report whether the venue network is visible at all; a weak signal is the usual failure.
  const int found = WiFi.scanNetworks();
  for (int i = 0; i < found; i++) Serial.printf("  seen %s ch%d %d dBm\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));
  Serial.printf("scan saw %d networks\n", found);
#endif
  beginStation();
  MDNS.begin("htn-robot");
  MDNS.addService("ws", "tcp", config::CONTROL_PORT);
  Serial.printf("access point '%s' up, control at ws://%s:%u/\n", config::AP_SSID,
                WiFi.softAPIP().toString().c_str(), config::CONTROL_PORT);
  socket.begin();
  socket.onEvent(onEvent);
}

void loop() {
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
  authority::tick();

#ifdef ROBOT_STA_SSID
  // The core's own reconnect gives up after a while; keep retrying the venue network.
  if (WiFi.status() == WL_CONNECTED) {
    staLostSince = 0;
  } else if (!staLostSince) {
    staLostSince = now;
  } else if (now - staLostSince > STA_RETRY_MS) {
    staLostSince = now;
    beginStation();
  }
#endif
}

bool snapshot(Command &out) { return authority::snapshot(out); }
bool estopLatched() { return authority::status().latched; }
uint8_t clientCount() { return clients; }

String stationIp() {
  if (WiFi.status() == WL_CONNECTED) return WiFi.localIP().toString();
  return String("-(") + static_cast<int>(WiFi.status()) + ")";
}

void broadcast(const char *json, size_t length) {
  for (uint8_t i = 0; i < WEBSOCKETS_SERVER_CLIENT_MAX; i++) {
    if (connectedClient[i] && !rejected[i] && millis() - lastHeard[i] <= QUIET_SKIP_MS) {
      socket.sendTXT(i, json, length);
    }
  }
}

}  // namespace server
