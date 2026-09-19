#pragma once

// Copy to secrets.h (git-ignored) and set a password of at least 8 characters.
// Anyone who joins this network can drive the robot.
#define ROBOT_AP_PASSWORD "change-me-please"

// Optional: also join this network so a laptop running the agent can reach the robot while
// keeping internet. Clients on it must connect with ws://<ip>:81/?token=ROBOT_AGENT_TOKEN.
// #define ROBOT_STA_SSID "venue-wifi"
// #define ROBOT_STA_PASSWORD "venue-password"
// #define ROBOT_AGENT_TOKEN "long-random-string"
