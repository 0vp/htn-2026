#pragma once
#include <Arduino.h>
void applyPacket(const char* data, size_t size, bool serialSource);
bool wirelessSupervision(bool enabled, bool renew = false);
String statusJson();
