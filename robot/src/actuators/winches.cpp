#include "winches.h"

#include <Arduino.h>

#include "../config.h"
#include "../pins.h"

namespace {

struct Winch {
  int8_t command = 0;
  int8_t lastMoved = 0;  // direction of the last run, to tell the two parallel end stops apart
  bool pressed = false;
  bool rawPressed = false;
  uint32_t rawSince = 0;
  int8_t blocked = 0;     // direction refused while the end stop is pressed
  float position = 0.5f;  // unknown at boot; snaps to 0 or 1 at the first end stop
};

Winch state[3];
bool standbyOff = false;

void drive(int i, int8_t dir) {
  digitalWrite(pins::WINCH_IN1[i], dir > 0 ? HIGH : LOW);
  digitalWrite(pins::WINCH_IN2[i], dir < 0 ? HIGH : LOW);
}

void readLimit(int i, uint32_t now) {
  Winch &w = state[i];
  const bool raw = digitalRead(pins::WINCH_LIMIT[i]) == LOW;
  if (raw != w.rawPressed) {
    w.rawPressed = raw;
    w.rawSince = now;
  }
  if (now - w.rawSince < config::LIMIT_DEBOUNCE_MS || raw == w.pressed) return;
  w.pressed = raw;
  if (w.pressed) {
    // The stop we hit is the one we were travelling towards. At boot (no travel yet) we
    // can't tell, so both directions stay allowed until the first run.
    w.blocked = w.lastMoved;
    if (w.lastMoved < 0) w.position = 0;
    if (w.lastMoved > 0) w.position = 1;
  } else {
    w.blocked = 0;
  }
}

}  // namespace

namespace winches {

void begin() {
  pinMode(pins::WINCH_STBY, OUTPUT);
  digitalWrite(pins::WINCH_STBY, LOW);
  for (int i = 0; i < 3; i++) {
    pinMode(pins::WINCH_IN1[i], OUTPUT);
    pinMode(pins::WINCH_IN2[i], OUTPUT);
    drive(i, 0);
    pinMode(pins::WINCH_LIMIT[i], INPUT_PULLUP);
  }
}

void set(const int8_t command[3]) {
  for (int i = 0; i < 3; i++) state[i].command = command[i] > 0 ? 1 : (command[i] < 0 ? -1 : 0);
}

void stop() {
  for (int i = 0; i < 3; i++) {
    state[i].command = 0;
    drive(i, 0);
  }
  digitalWrite(pins::WINCH_STBY, LOW);
  standbyOff = false;
}

void update(float dt) {
  const uint32_t now = millis();
  bool anyRunning = false;
  for (int i = 0; i < 3; i++) {
    Winch &w = state[i];
    readLimit(i, now);
    int8_t dir = w.command;
    if (dir != 0 && w.pressed && dir == w.blocked) dir = 0;
    drive(i, dir);
    if (dir != 0) {
      w.lastMoved = dir;
      w.position = constrain(w.position + dir * dt / config::WINCH_TRAVEL_S, 0.0f, 1.0f);
      anyRunning = true;
    }
  }
  if (anyRunning != standbyOff) {
    standbyOff = anyRunning;
    digitalWrite(pins::WINCH_STBY, anyRunning ? HIGH : LOW);
  }
}

float position(int winch) { return state[winch].position; }
bool atInEnd(int winch) { return state[winch].pressed && state[winch].lastMoved < 0; }
bool atOutEnd(int winch) { return state[winch].pressed && state[winch].lastMoved > 0; }

}  // namespace winches
