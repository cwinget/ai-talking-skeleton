# Body firmware (ESP32-S3-CAM)

Radar, camera, eye LEDs, mouth LED, and jaw servo. Implements the **body** role
of `PROTOCOL.md`.

## Flash it
Full walkthrough (PlatformIO install, Wi-Fi list, TLS/token): [`docs/FIRMWARE.md`](../../docs/FIRMWARE.md).

1. `cp include/config.example.h include/config.h` and edit it: up to three 2.4 GHz Wi-Fi
   networks, `SERVER_HOST` / `SERVER_PORT` / `SERVER_TLS` / `SERVER_TOKEN` (see "Network" below),
   and check the pin numbers match your wiring.
2. VS Code → **File → Open Folder** → `firmware/body` (or `pio run -t upload` from a terminal).
3. **Box power off**, then plug into the board's USB-C port labeled **TTL** (not OTG).
4. Click **→** (upload), then **🔌** (serial monitor).
   If upload can't connect: hold **BOOT**, tap **RST**, release **BOOT**, upload again.

## Boot self-test (before it ever talks to the server)
Watch the skeleton and the serial monitor:
1. red eyes light for 0.6 s
2. green eyes light for 0.6 s
3. mouth LED lights for 0.6 s
4. jaw moves closed → open → closed

Anything that doesn't light: check LED polarity (long leg toward the resistor/pin),
the pin number in `config.h`, and the ground wire.

The on-board RGB light shows status: **red** = no Wi-Fi, **yellow** = Wi-Fi but no
server, **green** = connected, **blue** = radar sees someone.

## Calibrate the jaw (live, recommended)
Open the server's admin UI (port 8080) → **Jaw calibration** card, with the box closed and the board
connected. "Hold" moves the jaw to an angle so you can find the closed and open positions,
"Sweep" shows the range; Save stores them in the board's flash. Saved values override
`JAW_CLOSED_DEG` / `JAW_OPEN_DEG` from `config.h` (the boot log shows which are in use), and
Reset reverts to the `config.h` values. Same thing over HTTP: `GET /api/jaw`,
`POST /api/jaw/test {"action":"hold","deg":100}`, `POST /api/jaw/config {"closed":90,"open":110}`
(see [`docs/ADMIN_API.md`](../../docs/ADMIN_API.md)).

## LED brightness (live)
Admin UI → **Eye & mouth brightness** card. "Hold at this level" shows a fixed brightness
(do it in the dark with the skull assembled), Save stores it in flash. Saved values override
`EYES_BRIGHTNESS` / `MOUTH_BRIGHTNESS` from `config.h`; Reset reverts. Brightness is perceptual
0-1 and scales the whole animation (idle glow, talking, flicker). HTTP:
`POST /api/leds/test {"target":"eyes","level":0.3}`, `POST /api/leds/config {"eyes":0.3,"mouth":0.5}`.

## Calibrate the jaw (by re-uploading)
**Before attaching the linkage**, set `JAW_CLOSED_DEG` and `JAW_OPEN_DEG` close
together (e.g. 90 and 100), flash, and watch the self-test sweep. Then attach
the horn/linkage with the servo at the closed angle and widen `JAW_OPEN_DEG`
a few degrees at a time until the mouth opens enough. If the jaw opens when it
should close, swap the two numbers. If the servo buzzes or strains at either
end, back that angle off: it's pushing against a hard stop.

## Run it with the ReSpeaker
```bash
python -m skeleton.server
```
No simulator needed: walking up to the radar starts a conversation, the camera
sends photos, the ReSpeaker talks, the jaw and mouth LED move with the voice,
and the eyes glow red (or green in family mode, with `FAMILY_EYES_GREEN 1`). Server log should show
both devices connecting (`device connected: respeaker-lite@... as audio`, then `skeleton-body@... as body`).

Tune `MOUTH_DELAY_MS` in `.env` until the jaw lines up with the voice.

## Watching the log over Wi-Fi
With the box on its own power (no USB needed), from any computer on the same network:
```bash
nc skeleton-body.local 23
```
(or `nc <board-ip> 23`; the IP is in your router's client list). You get everything
the serial monitor would show from the moment you connect, starting with a status
line (server connection, radar state). Ctrl-C to quit. One viewer at a time.

Don't power the board from your laptop's USB while the box is off: the laptop port
can't run the radar, servo, LEDs and ReSpeaker too. USB = flashing only.

## Radar debugging
The serial monitor prints radar status every 0.5 s, plus every OUT-pin change:
```
[radar] OUT pin went HIGH
[radar] => PRESENT (sent to server)
[radar] OUT=HIGH -> PRESENT | sees MOVING: moving 140cm (energy 62), still 150cm (energy 35)
```
- `OUT=` is the radar's own yes/no pin. `PRESENT`/`nobody` is the firmware's
  debounced decision (needs 0.25 s of HIGH to say present, 2 s of LOW to say gone).
- The `sees ...` part needs one extra wire: **radar TX -> GPIO41**. It shows what
  the radar detects and how far away. Without it you'll see `no data on GPIO41`.
- Turn the messages off with `#define RADAR_DEBUG 0` in `config.h`.
- Presence uses the OUT pin **or** the TX data by default (`RADAR_PRESENCE_SOURCE 2`), so
  either wire alone is enough. The log shows both: `OUT=low TX=yes -> PRESENT` means the
  TX data saw you and the OUT pin didn't (check that wire if you care).
- `RADAR_MAX_CM` ignores TX-data targets farther than that (needs source 1 to fully apply,
  since the OUT pin has no distance).

Note the radar keeps OUT high for its own "no-one duration" (5 s by default)
after you leave, so "gone" takes about 7 s. That's normal.

## Troubleshooting
- **`[camera] init failed`**: the ribbon cable is loose, or PSRAM isn't detected.
  Everything else keeps working without the camera.
- **Photos upside down / mirrored**: `CAM_VFLIP` / `CAM_HMIRROR` in `config.h`.
- **Radar never says PRESENT**: check the OUT pin wire (GPIO1) and that the
  radar's own LED reacts to you. **Always PRESENT**: it's seeing something
  moving (a fan, a curtain, the jaw!); narrow its range in the HLKRadarTool app.
- **Board resets when the jaw moves**: the servo is drawing power through the
  board. It must be on the 5 V rail with a shared ground, with the 100 µF caps at the servo (see `docs/HARDWARE.md`).

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
