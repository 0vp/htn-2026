#include "authority.h"

#include <Arduino.h>

#include "../config.h"

namespace {

constexpr uint8_t NOBODY = 0xFF;

Command latest;
uint8_t owner = NOBODY;
authority::Role ownerRole = authority::Role::None;
uint32_t ownerLastMs = 0;
uint8_t supervisor = NOBODY;
uint32_t supervisorLastMs = 0;
bool latched = true;  // boot in E-STOP: an operator must arm deliberately
// Guards everything above between the network and actuator tasks.
portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;

bool supervisedNow() { return supervisor != NOBODY && millis() - supervisorLastMs <= config::FAILSAFE_MS; }

void release(const char *why) {
  if (owner == NOBODY) return;
  const uint8_t was = owner;
  portENTER_CRITICAL(&lock);
  owner = NOBODY;
  ownerRole = authority::Role::None;
  latest = Command();
  portEXIT_CRITICAL(&lock);
  Serial.printf("control released (client %u, %s)\n", was, why);
}

void endSupervision(const char *why) {
  if (supervisor == NOBODY) return;
  portENTER_CRITICAL(&lock);
  supervisor = NOBODY;
  portEXIT_CRITICAL(&lock);
  Serial.printf("auto supervision ended (%s)\n", why);
  if (ownerRole == authority::Role::Agent) release("unsupervised");
}

void take(uint8_t client, authority::Role role, const Command &c, bool clearLatch) {
  if (owner == NOBODY) {
    portENTER_CRITICAL(&lock);
    owner = client;
    ownerRole = role;
    portEXIT_CRITICAL(&lock);
    Serial.printf("control taken by client %u (%s)\n", client, authority::roleName(role));
  }
  if (client != owner) return;
  portENTER_CRITICAL(&lock);
  if (clearLatch) latched = false;
  latest = c;
  ownerLastMs = millis();
  portEXIT_CRITICAL(&lock);
}

void supervise(uint8_t client, const Command &c) {
  if (!c.armed) {
    if (client == supervisor) endSupervision("badge disarmed");
    return;
  }
  if (supervisor != client) Serial.printf("auto supervision by client %u\n", client);
  portENTER_CRITICAL(&lock);
  supervisor = client;
  supervisorLastMs = millis();
  latched = false;  // a human arming in AUTO is a deliberate clear
  portEXIT_CRITICAL(&lock);
}

}  // namespace

namespace authority {

const char *roleName(Role role) {
  switch (role) {
    case Role::Human:
      return "human";
    case Role::Agent:
      return "agent";
    default:
      return "none";
  }
}

void onCommand(uint8_t client, bool local, const Command &c) {
  if (c.estop) {
    if (!latched) Serial.printf("E-STOP from client %u\n", client);
    portENTER_CRITICAL(&lock);
    latched = true;
    portEXIT_CRITICAL(&lock);
    release("e-stop");
    endSupervision("e-stop");
    return;
  }
  if (c.autoMode) {
    // Only the badge on the robot's own network may supervise; a venue-network client can't.
    if (local && c.source == Source::Badge) supervise(client, c);
    return;
  }
  if (c.source == Source::Agent) {
    if (!c.armed || latched || !supervisedNow()) {
      if (client == owner) release(latched ? "e-stop latched" : "agent disarmed or unsupervised");
      return;
    }
    take(client, Role::Agent, c, false);
    return;
  }
  if (!c.armed) {
    if (client == owner) release("disarmed");
    return;
  }
  take(client, Role::Human, c, true);
}

void onDisconnect(uint8_t client) {
  if (client == owner) release("disconnected");
  if (client == supervisor) endSupervision("badge disconnected");
}

void tick() {
  const uint32_t now = millis();
  if (owner != NOBODY && now - ownerLastMs > config::RELEASE_OWNER_MS) release("silent");
  if (supervisor != NOBODY && !supervisedNow()) endSupervision("badge silent");
}

bool snapshot(Command &out) {
  portENTER_CRITICAL(&lock);
  bool fresh = owner != NOBODY && !latched && millis() - ownerLastMs <= config::FAILSAFE_MS;
  if (ownerRole == Role::Agent && !supervisedNow()) fresh = false;
  out = latest;
  portEXIT_CRITICAL(&lock);
  return fresh;
}

Status status() {
  portENTER_CRITICAL(&lock);
  const Status s{ownerRole, supervisedNow(), latched};
  portEXIT_CRITICAL(&lock);
  return s;
}

}  // namespace authority
