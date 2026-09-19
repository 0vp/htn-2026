#include "buttons.h"

#include <Arduino.h>

#include "../board.h"

namespace {

const char *const NAMES[BUTTON_COUNT] = {"A", "B", "Home", "Down", "Left", "Right", "Up", "Aux1", "Start"};

constexpr uint32_t DEBOUNCE_MS = 15;

ButtonMap current{board::SR_DATA_DEFAULT, {0, 1, 2, 3, 4, 5, 6, 7}, false};
ButtonState state;
uint16_t candidate = 0;
uint32_t candidateSince = 0;

void pulse(int pin, int idle) {
  digitalWrite(pin, !idle);
  delayMicroseconds(2);
  digitalWrite(pin, idle);
  delayMicroseconds(2);
}

uint16_t sample() {
  const uint8_t raw = buttons::readRaw(current.dataPin);
  uint16_t bits = 0;
  for (uint8_t i = 0; i < 8; i++) {
    const bool level = raw & (1u << current.bitOf[i]);
    if (level == current.activeHigh) bits |= 1u << i;
  }
  if (digitalRead(board::BTN_START) == LOW) bits |= 1u << static_cast<uint8_t>(Button::Start);
  return bits;
}

}  // namespace

const char *buttonName(Button button) {
  const auto i = static_cast<uint8_t>(button);
  return i < BUTTON_COUNT ? NAMES[i] : "?";
}

namespace buttons {

void begin(const ButtonMap &map) {
  pinMode(board::SR_LOAD, OUTPUT);
  pinMode(board::SR_CLK, OUTPUT);
  digitalWrite(board::SR_LOAD, HIGH);
  digitalWrite(board::SR_CLK, LOW);
  pinMode(board::BTN_START, INPUT_PULLUP);
  setMap(map);
}

void setMap(const ButtonMap &map) {
  current = map;
  pinMode(current.dataPin, INPUT_PULLUP);
  candidate = sample();
  state.held = candidate;
}

const ButtonMap &map() { return current; }

uint8_t readRaw(int pin) {
  // LOAD low latches all eight inputs; the first one is then already on QH.
  pulse(board::SR_LOAD, HIGH);
  uint8_t raw = 0;
  for (uint8_t i = 0; i < 8; i++) {
    if (digitalRead(pin)) raw |= 1u << i;
    pulse(board::SR_CLK, LOW);
  }
  return raw;
}

const ButtonState &poll() {
  const uint16_t now = sample();
  const uint32_t ms = millis();
  if (now != candidate) {
    candidate = now;
    candidateSince = ms;
  }
  const uint16_t previous = state.held;
  if (ms - candidateSince >= DEBOUNCE_MS) state.held = candidate;
  state.pressed = state.held & ~previous;
  state.released = previous & ~state.held;
  return state;
}

}  // namespace buttons
