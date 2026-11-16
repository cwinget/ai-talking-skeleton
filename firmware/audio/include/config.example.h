// Copy this file to config.h and fill it in. config.h is not checked in.
#pragma once

// ---- network ----
// Up to three 2.4 GHz networks, in priority order: the board joins the first one it can
// see. Leave the backups "" if unused. Phone hotspot: iPhone -> turn on "Maximize
// Compatibility"; Android -> set the hotspot band to 2.4 GHz.
#define WIFI_SSID        "your-home-wifi"
#define WIFI_PASSWORD    "your-password"
#define WIFI_SSID_2      "your-phone-hotspot"
#define WIFI_PASSWORD_2  "hotspot-password"
#define WIFI_SSID_3      ""
#define WIFI_PASSWORD_3  ""

// Server: wss:// with a bearer token (the same host works on every network).
#define SERVER_HOST         "skeleton-ws.example.com"
#define SERVER_PORT         443
#define SERVER_TLS          1    // 0 = plain ws:// (e.g. SERVER_HOST "192.168.1.50", port 8765)
#define SERVER_VERIFY_CERT  1    // 0 = encrypt but skip the certificate check (last resort)
#define SERVER_TOKEN        "paste-your-token-here"

// Software output gain (1.0 = as sent by the server). The server can change it
// at runtime with {"type":"volume","gain":x}.
#define DEFAULT_GAIN  1.0f
