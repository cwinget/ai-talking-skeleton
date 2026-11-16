# Firmware

Two boards, two PlatformIO projects. Both are thin WebSocket clients of the server and speak
[`PROTOCOL.md`](../PROTOCOL.md):

| Folder | Board | Role | USB port to flash |
|---|---|---|---|
| `firmware/body` | ESP32-S3-CAM N16R8 (OV3660) | `body`: radar, camera, eyes, mouth LED, jaw | the one labeled **TTL** |
| `firmware/audio` | ReSpeaker Lite (XIAO ESP32-S3) | `audio`: mic + speaker | the **XIAO's** USB-C |
| `firmware/respeaker-test` | ReSpeaker Lite | standalone mic/speaker check, no server | the XIAO's USB-C |

Wiring and parts: [`HARDWARE.md`](HARDWARE.md).

## Toolchain

- [VS Code](https://code.visualstudio.com/) with the **PlatformIO IDE** extension, or the CLI
  (`pip install platformio`, then `pio`).
- The projects use the community **pioarduino** platform (Arduino core 3.x for ESP32-S3).
  PlatformIO downloads it on the first build; the URL is in each `platformio.ini`. The first
  build takes several minutes.
- Libraries are pulled automatically: `links2004/WebSockets`, `bblanchon/ArduinoJson` 7.

## The ReSpeaker needs its I2S XMOS firmware

The ReSpeaker Lite's XMOS chip ships with either a USB or an I2S firmware. This project needs
the **I2S** one, because the XIAO talks to the XMOS chip over I2S. Check with `dfu-util -l` and
flash it following Seeed's ReSpeaker Lite wiki if needed. Then run `firmware/respeaker-test`:
it beeps, records 4 s, prints mic levels and plays the recording back. If that works, the
audio hardware is fine.

## Configure: `include/config.h`

Each board has `include/config.example.h`. Copy it to `include/config.h` and edit the copy.
`config.h` holds your Wi-Fi passwords and device token, and it's git-ignored. Never commit it.

```bash
cd firmware/body  && cp include/config.example.h include/config.h
cd ../audio       && cp include/config.example.h include/config.h
```

### Network (both boards)

| Setting | Meaning |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | first-choice network |
| `WIFI_SSID_2`, `WIFI_SSID_3` (+ passwords) | backups, `""` if unused |
| `SERVER_HOST` | hostname or IP of the server (or of your reverse proxy) |
| `SERVER_PORT` | `443` behind a TLS proxy, `8765` for the server directly |
| `SERVER_TLS` | `1` = `wss://`, `0` = plain `ws://` |
| `SERVER_VERIFY_CERT` | `1` = check the certificate against `server_ca.h`. `0` = encrypted but unverified (last resort) |
| `SERVER_TOKEN` | must equal the server's `DEVICE_TOKEN`. `""` = no auth header |

The board joins the **highest-priority network in range**. It scans at boot and again after
15 s without a connection, so home Wi-Fi wins at home and a phone hotspot is used elsewhere.
The ESP32 only does **2.4 GHz**. iPhone hotspots need "Maximize Compatibility" on; Android
hotspots must be set to the 2.4 GHz band.

Two typical setups:

```c
// LAN, server on 10.0.0.20 (plain docker-compose.yml)
#define SERVER_HOST "10.0.0.20"
#define SERVER_PORT 8765
#define SERVER_TLS  0

// Internet, behind Traefik (docker-compose.traefik.example.yml)
#define SERVER_HOST "skeleton-ws.example.com"
#define SERVER_PORT 443
#define SERVER_TLS  1
#define SERVER_VERIFY_CERT 1
```

`include/server_ca.h` lists the root CAs the boards trust (Let's Encrypt, plus the CAs
Cloudflare uses). See [DEPLOY.md → Certificates](DEPLOY.md#certificates-the-boards-trust).
`skeleton_net.h` and `server_ca.h` are identical in both firmware folders. If you change one,
change both.

### Body only

| Setting | Default | Meaning |
|---|---|---|
| `PIN_RADAR`, `PIN_EYES_RED`, `PIN_EYES_GREEN`, `PIN_MOUTH_LED`, `PIN_SERVO` | 1, 21, 47, 42, 14 | see the pinout in HARDWARE.md |
| `RADAR_RX_PIN` | 41 | radar TX → this GPIO for distance data (`-1` = not wired) |
| `RADAR_PRESENCE_SOURCE` | 2 | 0 = OUT pin, 1 = TX data, 2 = either |
| `RADAR_MAX_CM` | 0 | ignore TX-data targets farther than this (0 = any) |
| `RADAR_DEBUG` | 1 | print radar status every 0.5 s |
| `FAMILY_EYES_GREEN` | 0 | 1 = green eyes in family mode, red in scary |
| `EYES_BRIGHTNESS`, `MOUTH_BRIGHTNESS` | 1.0 | defaults only. Values saved from the admin UI win |
| `JAW_CLOSED_DEG`, `JAW_OPEN_DEG` | 90, 110 | defaults only. Values saved from the admin UI win |
| `JAW_RELAX_WHEN_IDLE` | 1 | stop driving the servo when idle (no hum) |
| `CAM_VFLIP`, `CAM_HMIRROR` | 0 | fix upside-down / mirrored photos (or `CAMERA_ROTATE_180` on the server) |

### Audio only

| Setting | Default | Meaning |
|---|---|---|
| `DEFAULT_GAIN` | 1.0 | software output gain. The server can change it with a `volume` message |

## Flash

1. **Body board: turn box power off first.** The board is powered through its 5V pin, and
   laptop USB plus box power at the same time is asking for trouble. Laptop USB also can't
   run the servo, radar and LEDs, so use it only for flashing.
2. Open the firmware folder in VS Code (**File → Open Folder → `firmware/body`**). PlatformIO
   detects `platformio.ini`.
3. Plug into the right USB port (table above), click **→** (Upload), then **🔌** (Monitor,
   115200 baud).
   CLI: `pio run -t upload && pio device monitor`.
4. If upload can't connect: hold **BOOT**, tap **RST**, release **BOOT**, then upload again.

## First boot

**Body board** runs a self-test before connecting: red eyes, green eyes, mouth LED (0.6 s
each), then the jaw sweeps closed → open → closed. The on-board RGB LED shows status:

| Color | Meaning |
|---|---|
| red | no Wi-Fi |
| yellow | Wi-Fi, but no server connection |
| green | connected to the server |
| blue | radar sees someone |

**Audio board**: the XIAO's small orange LED is on while it's connected to the server. Every
30 s it prints a `[stats]` line with RSSI, underruns and mic drops.

On the server, the log shows `device connected: respeaker-lite@<ip> as audio` and
`device connected: skeleton-body@<ip> as body`. The admin UI's status card shows both.

## Logs without a cable

The body board copies its serial output to TCP port 23 and announces itself over mDNS:

```bash
nc skeleton-body.local 23      # or: nc <board-ip> 23
```

One viewer at a time. You get a status line first, then live output.

## Calibrate

Jaw angles and LED brightness are set live from the admin UI and saved in the body board's
flash. See [TUNING.md → Jaw and LEDs](TUNING.md#jaw-and-leds). No reflashing needed.

## Troubleshooting

Board-specific troubleshooting (radar, camera, Wi-Fi, I2S) is in
[`firmware/body/README.md`](../firmware/body/README.md) and
[`firmware/audio/README.md`](../firmware/audio/README.md). The most common problems:

- **`[ws] can't reach ...`**: check, in order: DNS for `SERVER_HOST`, the port and
  `SERVER_TLS` combination, the token (the server log says `bad token`), and that the
  certificate's CA is in `server_ca.h`.
- **ReSpeaker drops Wi-Fi more than the body board**: attach the U.FL antenna and move it away
  from the speaker magnet. See HARDWARE.md → Known issues.
