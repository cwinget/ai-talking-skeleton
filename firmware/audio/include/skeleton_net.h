// Shared network setup for the skeleton boards (same file in firmware/audio and firmware/body).
//
// Wi-Fi: up to three networks in PRIORITY order (WIFI_SSID first). At boot, and whenever
// the connection has been down for a while, the board scans and joins the highest-priority
// network it can see, so at home it prefers home Wi-Fi even if your phone hotspot is on.
//
// Server: wss:// (TLS) with a bearer token, verified against the root certificates in
// server_ca.h. Set SERVER_TLS 0 for a plain ws:// server on the LAN.
#pragma once

#include <WiFi.h>
#include <WebSocketsClient.h>

#include "config.h"
#include "server_ca.h"

// ---- defaults for settings older config.h files don't have ----
#ifndef WIFI_SSID_2
#define WIFI_SSID_2 ""
#endif
#ifndef WIFI_PASSWORD_2
#define WIFI_PASSWORD_2 ""
#endif
#ifndef WIFI_SSID_3
#define WIFI_SSID_3 ""
#endif
#ifndef WIFI_PASSWORD_3
#define WIFI_PASSWORD_3 ""
#endif
#ifndef SERVER_TLS
#define SERVER_TLS 1          // 1 = wss:// (TLS), 0 = plain ws://
#endif
#ifndef SERVER_VERIFY_CERT
#define SERVER_VERIFY_CERT 1  // 1 = check the server certificate against server_ca.h
#endif
#ifndef SERVER_TOKEN
#define SERVER_TOKEN ""       // sent as "Authorization: Bearer <token>"; empty = no header
#endif
#ifndef SERVER_PATH
#define SERVER_PATH "/"
#endif

namespace net {

struct Network {
  const char *ssid;
  const char *pass;
};
static const Network NETWORKS[] = {
    {WIFI_SSID, WIFI_PASSWORD},
    {WIFI_SSID_2, WIFI_PASSWORD_2},
    {WIFI_SSID_3, WIFI_PASSWORD_3},
};
static constexpr int NUM_NETWORKS = sizeof(NETWORKS) / sizeof(NETWORKS[0]);
static constexpr uint32_t RETRY_SAME_MS = 15000;  // down this long -> rescan and pick again

static Print *out = &Serial;
static int current = -1;      // index into NETWORKS
static int rotate = 0;        // used when no known network is visible
static bool wasUp = false;
static uint32_t attemptMs = 0;

inline const char *scheme() { return SERVER_TLS ? "wss" : "ws"; }

// Scan and return the highest-priority configured network in range, or -1.
inline int pickNetwork() {
  int found = WiFi.scanNetworks(false, false);  // blocking, ~2-3 s
  int best = -1;
  for (int i = 0; i < NUM_NETWORKS && best < 0; i++) {
    if (!NETWORKS[i].ssid[0]) continue;
    for (int j = 0; j < found; j++) {
      if (WiFi.SSID(j) == NETWORKS[i].ssid) {
        best = i;
        out->printf("[wifi] in range: %s (rssi %d)%s\n", NETWORKS[i].ssid, WiFi.RSSI(j),
                    i == 0 ? "" : " (backup)");
        break;
      }
    }
  }
  if (found >= 0) WiFi.scanDelete();
  return best;
}

inline void connectBest() {
  WiFi.disconnect(false, false);
  int i = pickNetwork();
  if (i < 0) {
    // Nothing we know is visible (or the scan failed): try each configured network in turn.
    do {
      i = rotate++ % NUM_NETWORKS;
    } while (!NETWORKS[i].ssid[0]);
    out->printf("[wifi] no known network in range, trying %s anyway\n", NETWORKS[i].ssid);
  }
  current = i;
  out->printf("[wifi] connecting to %s\n", NETWORKS[i].ssid);
  WiFi.begin(NETWORKS[i].ssid, NETWORKS[i].pass);
  attemptMs = millis();
}

// Call once in setup().
inline void wifiBegin(Print &log, const char *hostname) {
  out = &log;
  if (hostname) WiFi.setHostname(hostname);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);         // power save adds big latency spikes
  WiFi.setAutoReconnect(false); // we reconnect ourselves so we can switch networks
  connectBest();
}

// Call every loop().
inline void wifiService() {
  bool up = WiFi.status() == WL_CONNECTED;
  uint32_t now = millis();
  if (up) {
    if (!wasUp) {
      out->printf("[wifi] on %s, ip %s, rssi %d\n", WiFi.SSID().c_str(),
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
      wasUp = true;
    }
    return;
  }
  if (wasUp) {  // just dropped: retry the same network right away
    wasUp = false;
    out->printf("[wifi] lost %s, reconnecting\n", current >= 0 ? NETWORKS[current].ssid : "?");
    WiFi.begin(NETWORKS[current].ssid, NETWORKS[current].pass);
    attemptMs = now;
    return;
  }
  if (now - attemptMs > RETRY_SAME_MS) connectBest();
}

inline const char *ssid() { return current >= 0 ? NETWORKS[current].ssid : "-"; }

// Configure the WebSocket client for the server in config.h. Call once in setup().
inline void wsBegin(WebSocketsClient &ws) {
#if SERVER_TLS
#if SERVER_VERIFY_CERT
  ws.beginSslWithCA(SERVER_HOST, SERVER_PORT, SERVER_PATH, SERVER_ROOT_CA);
#else
  ws.beginSSL(SERVER_HOST, SERVER_PORT, SERVER_PATH);  // encrypted, but server not verified
#endif
#else
  ws.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
#endif
  if (SERVER_TOKEN[0]) {
    String h = String("Authorization: Bearer ") + SERVER_TOKEN;
    ws.setExtraHeaders(h.c_str());  // the library keeps its own copy
  }
  out->printf("server: %s://%s:%d%s%s\n", scheme(), SERVER_HOST, SERVER_PORT, SERVER_PATH,
              SERVER_TOKEN[0] ? " (with token)" : " (NO token)");
}

// Call every loop(): every 10 s while Wi-Fi is up but the server isn't, say so.
inline void wsWatch(bool wsConnected) {
  static uint32_t downSince = 0, lastMsg = 0;
  uint32_t now = millis();
  if (wsConnected || WiFi.status() != WL_CONNECTED) {
    downSince = 0;
    return;
  }
  if (!downSince) downSince = now;
  if (now - downSince > 10000 && now - lastMsg > 10000) {
    lastMsg = now;
    out->printf("[ws] can't reach %s://%s:%d for %us (DNS, certificate, token or server down?)\n",
                scheme(), SERVER_HOST, SERVER_PORT, (unsigned)((now - downSince) / 1000));
  }
}

}  // namespace net
