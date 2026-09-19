#include <cassert>
#include <cstring>
#include "../src/protocol.h"

int main() {
  SteeringControl c;
  auto send = [&](const char* packet, uint32_t now) { handlePacket(packet, strlen(packet), c, now); };
  send(R"({"type":"supervise","enabled":true})", 0);
  send(R"({"type":"command","armed":true,"estop":false,"drive":{"duty":0.2,"steering_deg":10}})", 10);
  assert(c.active && c.duty == .2f && c.steering == 10);
  send(R"({"type":"command","armed":true,"estop":false,"drive":{"left":1,"right":-1}})", 20);
  assert(!c.active && c.duty == 0);
  send(R"({"type":"command","armed":true,"estop":false,"drive":{"duty":0.1,"steering_deg":-20}})", 30);
  assert(c.active && c.steering == -20);
  send("not json", 31); assert(!c.active);
  send(R"({"type":"command","armed":true,"estop":true})", 40);
  assert(c.estop && !c.active);  // Stop wins even if drive fields are missing.
  send(R"({"type":"supervise","enabled":true})", 50);
  send(R"({"type":"command","armed":true,"estop":false,"drive":{"duty":0.1,"steering_deg":0}})", 60);
  assert(c.estop && !c.active);
}
