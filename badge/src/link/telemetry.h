#pragma once

#include <math.h>
#include <stdint.h>

/**
 * The subset of the dashboard's Telemetry (fe/src/telemetry/types.ts) the badge shows.
 * The robot may send any subset of fields; missing values stay NAN / false.
 */
struct Telemetry {
  float packVolts = NAN;
  float rpmLeft = NAN;
  float rpmRight = NAN;
  float winchPos[3] = {NAN, NAN, NAN};
  bool limits[3][2] = {{false, false}, {false, false}, {false, false}};
  int robotRssi = 0;
  bool hasPose = false;
  float poseX = 0, poseZ = 0, poseYaw = 0;
  uint32_t updatedMs = 0;
};

/** 3S LiPo resting-voltage to charge estimate, matching the dashboard's curve. */
inline float stateOfCharge(float volts) {
  static const float curve[][2] = {{3.3f, 0},     {3.6f, 0.1f},  {3.7f, 0.3f},  {3.75f, 0.45f}, {3.8f, 0.55f},
                                   {3.85f, 0.65f}, {3.95f, 0.8f}, {4.1f, 0.95f}, {4.2f, 1}};
  const float cell = volts / 3;
  if (isnan(cell) || cell <= curve[0][0]) return 0;
  for (int i = 1; i < 9; i++) {
    if (cell <= curve[i][0]) {
      return curve[i - 1][1] + (cell - curve[i - 1][0]) / (curve[i][0] - curve[i - 1][0]) * (curve[i][1] - curve[i - 1][1]);
    }
  }
  return 1;
}
