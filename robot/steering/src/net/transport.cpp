#include "network.h"
#include <WebSocketsServer.h>
#include "../runtime.h"
namespace network {
namespace {
WebSocketsServer socket(81);
int owner = -1;
void event(uint8_t client, WStype_t type, uint8_t* data, size_t length) {
  if (type == WStype_CONNECTED) {
    String expected = "/?token=" + password();
    String path(reinterpret_cast<char*>(data), length);
    if (owner >= 0 || path != expected) { socket.disconnect(client); return; }
    wirelessSupervision(false);
    owner = client;
  } else if (type == WStype_DISCONNECTED && owner == client) {
    owner = -1; wirelessSupervision(false);
  } else if (owner == client && type == WStype_TEXT) {
    // Agent commands cannot grant their own human-supervision lease.
    applyPacket(reinterpret_cast<char*>(data), length, false);
  } else if (owner == client && type != WStype_PING && type != WStype_PONG) {
    wirelessSupervision(false);
    socket.disconnect(client);
  }
}
}
bool hasController() { return owner >= 0; }
void transportBegin() { socket.begin(); socket.onEvent(event); }
void transportPoll() { socket.loop(); }
void publish(const String& state) {
  if (owner >= 0) socket.sendTXT(uint8_t(owner), state.c_str(), state.length());
}
}
