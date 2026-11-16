// Copy to config.h and fill in. config.h is not checked in.
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

// ---- pins (see the wiring diagram) ----
#define PIN_RADAR       1    // LD2410C OUT
#define PIN_EYES_RED    21   // red eye LEDs (scary mode)
#define PIN_EYES_GREEN  47   // green eye LEDs (family mode)
#define PIN_MOUTH_LED   42   // mouth LED(s)
#define PIN_SERVO       14   // jaw servo signal (orange)

// ---- radar debugging ----
#define RADAR_DEBUG     1    // print what the radar sees to the serial monitor
#define RADAR_RX_PIN    41   // optional: wire radar TX -> GPIO41 for distance readings (-1 = not wired)
// Presence comes from: 0 = OUT pin only, 1 = radar TX data only, 2 = either (default).
#define RADAR_PRESENCE_SOURCE 2
// TX data only counts targets closer than this many cm (0 = any distance). E.g. 300 to
// ignore people on the sidewalk. The OUT pin can't do this; use source 1 if you set it.
#define RADAR_MAX_CM    0

// ---- eyes ----
// 1 = green eyes in family mode, red in scary. 0 = always red (e.g. if your green LEDs are too dim).
#define FAMILY_EYES_GREEN 0
// Max brightness, 0..1 (perceptual: 0.5 looks about half as bright). Defaults only:
// values set live from the admin UI ("Eye & mouth brightness") are saved in flash and win.
#define EYES_BRIGHTNESS   1.0
#define MOUTH_BRIGHTNESS  1.0

// ---- jaw ----
// Servo angles for a closed and a fully open jaw. Find them with the jaw attached:
// start close together (e.g. 90 / 105) and widen. Swap them if the jaw moves backwards.
#define JAW_CLOSED_DEG  90
#define JAW_OPEN_DEG    110
// 1 = stop driving the servo when the jaw is closed and quiet (no idle buzzing).
#define JAW_RELAX_WHEN_IDLE 1

// ---- camera ----
#define CAM_VFLIP    0   // set to 1 if photos come out upside down
#define CAM_HMIRROR  0   // set to 1 if photos are mirrored
