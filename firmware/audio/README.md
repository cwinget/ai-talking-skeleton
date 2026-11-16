# Audio device firmware (ReSpeaker Lite + XIAO ESP32-S3)

Turns the ReSpeaker into the skeleton's **audio** device: it streams the XMOS
noise-suppressed mic to the server and plays whatever the server sends.

## Setup
Full walkthrough: [`docs/FIRMWARE.md`](../../docs/FIRMWARE.md). The ReSpeaker needs its
**I2S** XMOS firmware (not the USB one); check with `dfu-util -l`.

1. `cp include/config.example.h include/config.h` and edit it: Wi-Fi list (2.4 GHz only),
   `SERVER_HOST` / `SERVER_PORT` / `SERVER_TLS` / `SERVER_TOKEN` (see "Network" below).
2. Open this folder (`firmware/audio`) in VS Code. PlatformIO picks it up.
3. Plug into the **XIAO's** USB-C port, click **→** (upload), then **🔌** (serial monitor).

## What the serial monitor should show
```
=== skeleton audio device (ReSpeaker Lite) ===
ring buffer: 15 s (PSRAM)
[wifi] in range: your-home-wifi (rssi -61)
[wifi] connecting to your-home-wifi
[wifi] on your-home-wifi, ip 10.0.0.73, rssi -61
server: wss://skeleton-ws.example.com:443/ (with token)
[ws] connected
```
The XIAO's small orange LED is **on while connected** to the server.
Every 30 s it prints a `[stats]` line: `underruns` > 0 means Wi-Fi hiccups caused audio gaps;
`mic_drops` > 0 means Wi-Fi couldn't keep up with the mic; `rssi` below about -75 dBm means
weak signal (attach the antenna).

## Troubleshooting
- **Stuck on `[wifi] connecting to ...`**: wrong password, or a 5 GHz-only network.
- **Wi-Fi ok but never `[ws] connected`**: wrong `SERVER_HOST`/port, wrong
  `SERVER_TOKEN` (the server logs `rejected device connection ... bad token`), server not
  running, or a firewall on the server machine (on macOS, allow incoming connections
  for Python). With `SERVER_TLS 1` the host must have a certificate from a CA in
  `include/server_ca.h`.
- **`[mic] I2S read timeout`**: the XMOS chip isn't clocking I2S; recheck the
  XMOS firmware (`dfu-util -l`).
- **Speaker silent but the test sketch worked**: check the server log shows
  `device connected: respeaker-lite@... as audio` and that the trigger reached the server.

## Network (Wi-Fi list + wss)
`config.h` takes up to three Wi-Fi networks in priority order (`WIFI_SSID`, `WIFI_SSID_2`,
`WIFI_SSID_3`). At boot, and after 15 s without a connection, the board scans and joins the
highest-priority one in range, so home Wi-Fi wins at home and the phone hotspot is used
elsewhere. Hotspots must be 2.4 GHz (iPhone: "Maximize Compatibility").

The server connection is `wss://SERVER_HOST:443` with `Authorization: Bearer SERVER_TOKEN`,
checked against the root certificates in `include/server_ca.h` (Let's Encrypt + the
authorities Cloudflare uses). If the log keeps saying `[ws] can't reach ...`, check DNS,
the token, and that the server is up; `SERVER_VERIFY_CERT 0` skips the certificate check as
a last resort. `SERVER_TLS 0` + a LAN IP and port 8765 goes back to plain `ws://`.
