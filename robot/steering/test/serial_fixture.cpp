// Native protocol fixture: same parser and watchdog, no GPIO or physical hardware.
#include <chrono>
#include <iostream>
#include <poll.h>
#include <string>
#include <unistd.h>
#include "../src/protocol.h"

int main() {
  SteeringControl state;
  auto start = std::chrono::steady_clock::now();
  std::string buffer;
  while (true) {
    pollfd descriptor{STDIN_FILENO, POLLIN, 0};
    const int ready = poll(&descriptor, 1, 20);
    const auto elapsed = std::chrono::steady_clock::now() - start;
    uint32_t now = std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
    if (ready > 0) {
      char bytes[256];
      const auto size = read(STDIN_FILENO, bytes, sizeof(bytes));
      if (size <= 0) break;
      buffer.append(bytes, size);
      size_t end;
      while ((end = buffer.find('\n')) != std::string::npos) {
        handlePacket(buffer.data(), end, state, now);
        buffer.erase(0, end+1);
      }
    }
    state.tick(now);
    JsonDocument doc;
    doc["type"] = "telemetry";
    doc["drivetrain"] = "single_steer_v1";
    doc["motor_duty"] = state.duty;
    doc["steering_deg"] = state.steering;
    doc["encoder_ticks"] = 0;
    doc["control"]["supervised"] = state.supervised;
    doc["control"]["estop"] = state.estop;
    doc["control"]["owner"] = state.active ? "agent" : "none";
    doc["capabilities"]["drive_base"] = true;
    serializeJson(doc, std::cout);
    std::cout << std::endl;
  }
}
