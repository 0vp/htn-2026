#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
namespace network {
void begin();
void printSetup();
void poll();
void publish(const String& state);
bool hasController();
void describe(JsonDocument& doc);
String password();
void webBegin();
void webPoll();
void transportBegin();
void transportPoll();
void configure(const String& ssid, const String& passphrase);
}
