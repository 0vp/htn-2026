#include <cassert>
#include <limits>
#include "../src/control.h"
int main() {
  SteeringControl c;
  assert(!c.active && c.duty == 0);
  assert(!c.command(true, false, .1f, 0, 0));
  c.supervise(true);
  assert(c.command(true, false, .2f, -15, 1));
  c.tick(302); assert(!c.active && c.duty == 0);
  assert(c.command(true, false, -.2f, 20, 400));
  assert(!c.command(true, false, .4f, 0, 401));
  assert(!c.active);
  assert(!c.command(true, false, .1f, 21, 402));
  assert(!c.command(true, false, std::numeric_limits<float>::quiet_NaN(), 0, 403));
  assert(c.command(true, false, .1f, 0, UINT32_MAX-50));
  c.tick(251); assert(!c.active);  // millis wraparound still expires.
  assert(c.command(true, false, .1f, 0, 500));
  c.supervise(false); assert(!c.active);
  c.supervise(true);
  assert(!c.command(true, true, .1f, 0, 501));
  c.supervise(true);
  assert(!c.command(true, false, .1f, 0, 502));  // E-stop stays latched until reboot.
}
