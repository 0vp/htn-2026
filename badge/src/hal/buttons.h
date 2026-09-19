#pragma once

#include <stdint.h>

/** Logical inputs. The first eight come through the 74HC165; START has its own pin. */
enum class Button : uint8_t { A, B, Home, Down, Left, Right, Up, Aux1, Start, Count };

constexpr uint8_t BUTTON_COUNT = static_cast<uint8_t>(Button::Count);

const char *buttonName(Button button);

/** Debounced snapshot. `pressed` is edge-triggered and valid for one poll. */
struct ButtonState {
  uint16_t held = 0;
  uint16_t pressed = 0;
  uint16_t released = 0;

  bool isHeld(Button b) const { return held & (1u << static_cast<uint8_t>(b)); }
  bool wasPressed(Button b) const { return pressed & (1u << static_cast<uint8_t>(b)); }
  bool wasReleased(Button b) const { return released & (1u << static_cast<uint8_t>(b)); }
};

/**
 * Shift-register layout. `bitOf[i]` is the shift position (0 = first bit out) that carries
 * logical button i. Buttons pull their input low when pressed unless `activeHigh` is set.
 */
struct ButtonMap {
  int dataPin;
  uint8_t bitOf[8];
  bool activeHigh;
};

namespace buttons {

void begin(const ButtonMap &map);
void setMap(const ButtonMap &map);
const ButtonMap &map();

/** Raw 8 bits as shifted out, first bit in bit 0, sampled from `pin`. */
uint8_t readRaw(int pin);

/** Reads, debounces and returns the current state. Call every loop. */
const ButtonState &poll();

}  // namespace buttons
