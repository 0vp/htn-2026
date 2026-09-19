#include "network.h"
#include <WebServer.h>
#include "page.h"
#include "../runtime.h"
namespace network {
namespace {
WebServer web(80);
bool authorized(bool mutation = false) {
  if (!web.authenticate("robot", password().c_str())) {
    web.requestAuthentication(); return false;
  }
  if (mutation && web.header("X-Robot-Control") != "1") {
    web.send(403, "text/plain", "Use the robot setup page"); return false;
  }
  return true;
}
}
void webBegin() {
  const char* headers[] = {"X-Robot-Control"};
  web.collectHeaders(headers, 1);
  web.on("/", HTTP_GET, [] {
    if (authorized()) web.send_P(200, "text/html", ROBOT_PAGE);
  });
  web.on("/status", HTTP_GET, [] { web.send(200, "application/json", statusJson()); });
  web.on("/supervise", HTTP_POST, [] {
    if (!authorized(true)) return;
    bool enabled = web.arg("enabled") == "1";
    if (enabled && !hasController()) {
      web.send(409, "text/plain", "Connect the agent before enabling supervision"); return;
    }
    if (!wirelessSupervision(enabled, web.arg("renew") == "1")) {
      web.send(409, "text/plain", "Supervision expired; explicitly enable again"); return;
    }
    web.send(200, "application/json", "{\"ok\":true}");
  });
  web.on("/network", HTTP_POST, [] {
    if (!authorized(true)) return;
    String ssid = web.arg("ssid"), pass = web.arg("password");
    if (!ssid.length() || ssid.length() > 32 || pass.length() > 63 ||
        (pass.length() && pass.length() < 8)) {
      web.send(400, "text/plain", "Use a valid SSID and an 8–63 character password (or empty for an open network)"); return;
    }
    configure(ssid, pass);
    web.send(200, "application/json", "{\"saved\":true}");
  });
  web.begin();
}
void webPoll() { web.handleClient(); }
}
