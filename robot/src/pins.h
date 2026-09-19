#pragma once

/**
 * ELEGOO ESP32 (ESP-WROOM-32) wiring. Every pin below exists on both the 38- and 30-pin boards.
 * GPIO 6-11 are the module's flash; GPIO 1/3 stay free for the USB serial console.
 * The ESP32-S3-CAM is a separate board that only runs the camera.
 */
namespace pins {

// BTS7960 x2. R_EN and L_EN of both modules share DRIVE_EN, which needs a 10k pull-down:
// GPIO12 is a strap that must be low at boot, so the pull-down also keeps the motors off.
constexpr int DRIVE_EN = 12;
constexpr int LEFT_RPWM = 25;   // forward
constexpr int LEFT_LPWM = 26;   // reverse
constexpr int RIGHT_RPWM = 27;  // forward
constexpr int RIGHT_LPWM = 33;  // reverse

// Walfront encoders, powered from 3.3V. Input-only pins with no internal pulls: add 10k
// pull-ups to 3.3V if the encoder outputs are open collector.
constexpr int LEFT_ENC_A = 34;
constexpr int LEFT_ENC_B = 35;
constexpr int RIGHT_ENC_A = 36;  // "VP" on the silkscreen
constexpr int RIGHT_ENC_B = 39;  // "VN" on the silkscreen

// Servo signals. Servo power comes from the 6.0V rail, never from the ESP32.
constexpr int SERVO_SHOULDER = 13;
constexpr int SERVO_ELBOW = 14;
constexpr int SERVO_WRIST = 23;

// TB6612FNG x2 for the three N20 winches. PWMA/PWMB are tied to 3.3V; direction and on/off
// come from IN1/IN2. STBY of both boards shares one pin with a 10k pull-down (GPIO2 is a
// strap that must be low for flashing; the board's blue LED lights while winches are enabled).
constexpr int WINCH_STBY = 2;
constexpr int WINCH_IN1[3] = {4, 17, 19};
constexpr int WINCH_IN2[3] = {16, 18, 21};

// Each winch's two end stops are wired in parallel to one input (switch to GND, internal
// pull-up). The firmware knows which end was hit from the direction the winch was moving.
constexpr int WINCH_LIMIT[3] = {5, 15, 22};

// Pack voltage through a 100k / 27k divider (12.6V -> 2.68V) on an ADC1 pin.
constexpr int BATTERY_SENSE = 32;

}  // namespace pins
