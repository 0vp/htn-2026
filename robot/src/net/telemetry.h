#pragma once

#include <stddef.h>

/**
 * Builds the telemetry frame the dashboard merges (fe/src/telemetry/types.ts) and the badge
 * shows. Fields that aren't measured on this build (rpm before encoder calibration) are left out.
 */
namespace telemetry {

void begin();

/** Samples sensors; call every loop. */
void update();

/** Writes the JSON frame; returns its length, or 0 if `size` was too small. */
size_t build(char *out, size_t size, float loopHz);

float packVolts();

}  // namespace telemetry
