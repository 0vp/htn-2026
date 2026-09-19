#include <cassert>
#include <cstring>
#include "../src/protocol.h"
int main() {
  SteeringControl c;
  const char* grant = R"({"type":"supervise","enabled":true})";
  handlePacket(grant, strlen(grant), c, 1, false);
  assert(!c.supervised);  // A WebSocket controller cannot authorize itself.
  c.superviseFor(10);
  for (uint32_t now=20; now<=2010; now+=10) {
    c.command(true, false, .1f, 0, now);
    c.tick(now);
  }
  assert(c.active);
  c.tick(2011);
  assert(!c.supervised && !c.active);  // Commands do not extend human supervision.
  c.superviseFor(UINT32_MAX-20);
  c.command(true, false, .1f, 0, UINT32_MAX-10);
  c.tick(1990);
  assert(!c.supervised && !c.active);  // Lease also expires across millis wrap.
  c.superviseFor(3000);
  c.command(true, false, .1f, 0, 3001);
  c.tick(3302);
  assert(!c.active && !c.supervised);  // Motor expiry stays 300ms even with fresh supervision.
  c.supervise(false);
  assert(!c.supervised);
}
