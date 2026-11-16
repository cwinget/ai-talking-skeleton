# Deploying the server

The server is a single Python process (`python -m skeleton.server`) with two ports:

| Port | What | Who connects | Auth |
|---|---|---|---|
| **8765** (`PORT`) | device WebSocket | the two ESP32 boards, the simulator, `aux` listeners | `Authorization: Bearer <DEVICE_TOKEN>` (if set) |
| **8080** (`ADMIN_PORT`) | admin UI + HTTP API | you, from a phone or laptop | **none**: protect it yourself |

You can run it directly with Python (see the README quick start) or in Docker.

## Docker

```bash
cp .env.example .env            # then edit: GEMINI_API_KEY, DEVICE_TOKEN, ...
docker compose up -d --build
docker compose logs -f
```

The plain `docker-compose.yml` publishes both ports on the host. The boards then use
`SERVER_TLS 0`, `SERVER_HOST "<host LAN IP>"` and `SERVER_PORT 8765`. Open the admin UI at
`http://<host>:8080`. That setup is fine on a home LAN. For anything reachable from the
internet, use TLS and authentication ([Behind Traefik](#behind-traefik)). Note that
Docker-published ports bypass host firewalls like ufw.

The admin API rejects cross-site browser requests (a POST whose `Origin` doesn't match the
host gets 403), so a random web page open on a phone on your Wi-Fi can't drive the skeleton.
That is not a substitute for a password: anyone who can reach port 8080 directly can use it.

### The `data/` volume

`./data` is mounted at `/data`. The Dockerfile points every runtime path there:

| Host path | Contents |
|---|---|
| `data/greetings/<mode>/lines.txt` | greeting lines, one per line. Created from defaults in `skeleton/prompts.py` the first time greetings are generated (needs an API key) |
| `data/greetings/<mode>/greet_*.wav`, `greetings.json` | generated greeting audio (needs `GEMINI_API_KEY`) |
| `data/greetings/<mode>/phrases/` | random-phrase lines and audio |
| `data/settings.json` | admin UI overrides (voice, FX, timing, music file/volume) |
| `data/mode.txt` | persona override written by the admin UI (`auto` / `family` / `scary`) |
| `data/ambient/*.mp3` | background music. **None ships with this repo**; add your own royalty-free mp3 |
| `data/photos/` | camera frames, only if `PHOTOS_KEEP` > 0 |

The container runs as an unprivileged `skeleton` user. If the log shows `Permission denied`
under `/data`, make the folder writable by that user, e.g. `sudo chown -R 1000:1000 data`
(`docker compose exec skeleton-brain id` shows the uid).

Regenerate greetings after changing a voice or `lines.txt`, then restart:

```bash
docker compose exec skeleton-brain python -m skeleton.greetings --mode scary
docker compose restart
```

## Device token

Set `DEVICE_TOKEN` before the device port is reachable from anywhere you don't trust.
Without a token, anyone who can reach port 8765 can connect as the audio device and listen to
the porch mic, or connect as the body and receive camera requests.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the same value in `.env` (`DEVICE_TOKEN=`), in both boards' `config.h`
(`SERVER_TOKEN`), and pass it to the simulator with `--token` (or export `DEVICE_TOKEN`).
Connections without the right token get HTTP 401 before any WebSocket opens. The server
logs `rejected device connection from <ip>: bad token`.

The token travels in an HTTP header, so over plain `ws://` anyone on the network path can
read it. Use `wss://` off your LAN.

## Behind Traefik

This is how the original skeleton ran. Traefik sits in front of the container and
provides:

- a real TLS certificate (Let's Encrypt), so the boards connect with `wss://` and verify it;
- **password protection for the admin UI**, which has no login of its own;
- one stable hostname, so the same firmware works on home Wi-Fi and on a phone hotspot.

Use **two hostnames**, one per port:

| Host (example) | Router → service port | Middleware |
|---|---|---|
| `skeleton.example.com` | admin → **8080** | **basic auth** (or forward-auth: Authelia, Authentik, …) |
| `skeleton-ws.example.com` | device WebSocket → **8765** | **none** |

[`docker-compose.traefik.example.yml`](../docker-compose.traefik.example.yml) is a complete
example. It assumes you already run Traefik with:

- a Docker provider, and an external Docker network both containers join (`proxy` in the
  example);
- entrypoints `web` (:80) and `websecure` (:443);
- a certificate resolver (`letsencrypt` in the example).

Rename those to match your setup, then:

1. **DNS**: point both hostnames at your Traefik host.
2. **Admin password**: `htpasswd -nbB admin 'a-long-password'` (from `apache2-utils`).
   Paste the result into the `basicauth.users` label and **double every `$`**: compose treats
   `$` as variable interpolation.
3. **Token**: set `DEVICE_TOKEN` in `.env` (see above).
4. `docker compose -f docker-compose.traefik.example.yml up -d --build`
5. **Boards**: `SERVER_HOST "skeleton-ws.example.com"`, `SERVER_PORT 443`, `SERVER_TLS 1`,
   `SERVER_VERIFY_CERT 1`, `SERVER_TOKEN "<DEVICE_TOKEN>"`.

How the pieces fit together:

- **WebSockets need no special Traefik config.** Traefik forwards the HTTP `Upgrade` request
  to port 8765 and keeps the connection open. TLS ends at Traefik, and the app sees plain `ws://`.
- **Don't put basic auth on the device router.** The boards can't answer a basic-auth
  challenge. They send `Authorization: Bearer …`, and the app checks it during the WebSocket
  handshake. Basic auth would also claim the same `Authorization` header.
- **Don't publish 8765/8080 on the host** in this setup (the example has no `ports:`).
  Otherwise the unauthenticated admin UI is reachable around Traefik. That is also why the
  example is used with `-f` *instead of* `docker-compose.yml`. Copying it to
  `docker-compose.override.yml` would merge in the plain file's `ports:`.
- The server logs the client IP from the first `X-Forwarded-For` hop, which Traefik sets.
- Any reverse proxy that forwards WebSocket upgrades works the same way (Caddy, nginx with
  `proxy_set_header Upgrade/Connection`). Only the example file is Traefik-specific.

If you already define middlewares in Traefik's file provider, you can reference them
instead, e.g. `traefik.http.routers.skeleton-admin.middlewares=my-auth@file`.

### Certificates the boards trust

The boards check the server's certificate against the root CAs compiled into
`firmware/*/include/server_ca.h`:

- **Let's Encrypt** (ISRG Root X1/X2): Traefik serving its own certificate, including a
  DNS-only Cloudflare record or a LAN DNS rewrite to Traefik.
- **Google Trust Services** and **SSL.com**: the CAs Cloudflare uses when the record is
  **proxied** (orange cloud). Cloudflare proxies WebSockets.

If your certificate comes from a different CA (ZeroSSL, a private CA, …), add its root
certificate to both copies of `server_ca.h` and reflash. As a last resort,
`SERVER_VERIFY_CERT 0` keeps the connection encrypted but skips the check, which makes it
open to man-in-the-middle attacks.

### Checking it

```bash
# Admin UI: should ask for the password (401 without it)
curl -I https://skeleton.example.com/

# Device route: 401 without the token...
curl -i https://skeleton-ws.example.com/ -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
     -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=='
# ...and 101 Switching Protocols with it
curl -i https://skeleton-ws.example.com/ -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
     -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
     -H "Authorization: Bearer $DEVICE_TOKEN" --max-time 3

# Full simulator through Traefik
python -m skeleton.sim_client --url wss://skeleton-ws.example.com --token "$DEVICE_TOKEN"
```

The server log should show `device connected: <name>@<your public IP> as both`.

## `.env` reference

Every setting is read in `skeleton/config.py`. Settings marked ★ can also be changed live in
the admin UI. Those overrides are stored in `settings.json`, win over `.env`, and apply from
the next conversation. "Reset to .env" in the admin UI clears them.

**API and models**

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | blank | blank = echo mode (no API calls) |
| `LIVE_MODEL` | `gemini-3.8-live` | Live (voice) model |
| `VISION_MODEL` | `gemini-3.8-flash` | costume description model |
| `BRAIN` | `gemini` | `echo` forces echo mode even with a key |

**Voice and persona**

| Variable | Default | Meaning |
|---|---|---|
| `VOICE` ★ | `Charon` | Live voice name |
| `CHARACTER_NAME` ★ | `Old Bones` | the skeleton's name in the prompts |
| `CANDY_RULE` ★ | one-piece reminder | extra instruction added to both personas |
| `PERSONA_MODE` | `auto` | `auto` / `family` / `scary`. `mode.txt` beats it |
| `SCARY_START` / `SCARY_END` | `20:30` / `05:00` | auto mode's scary window (24 h local time, may wrap midnight) |
| `PRETEND_TIME` | blank | testing: pretend it's `HH:MM` |
| `SCARY_VOICE` ★, `SCARY_FX_PITCH_SEMITONES` ★, `SCARY_FX_REVERB` ★, `SCARY_FX_DRIVE_DB` ★ | blank | scary-mode overrides; blank = same as family |

**Voice effects**

| Variable | Default | Meaning |
|---|---|---|
| `FX_ENABLED` | `true` | voice effects on/off |
| `FX_PITCH_SEMITONES` ★ | `-4` | negative = deeper |
| `FX_REVERB` ★ | `0.3` | reverb wet level, 0-1 |
| `FX_DRIVE_DB` ★ | `0` | distortion, 0 = off |
| `FX_GAIN_DB` ★ | `0` | output gain |
| `FX_TAIL_S` | `0.4` | reverb tail played after each reply |

**Conversation**

| Variable | Default | Meaning |
|---|---|---|
| `MAX_CONVERSATION_S` ★ | `90` | then it says goodbye |
| `MAX_TURNS` ★ | `6` | skeleton replies per visitor |
| `SILENCE_TIMEOUT_S` ★ | `8` | silence before one nudge, then the end |
| `COOLDOWN_S` ★ | `10` | ignore the radar this long after a conversation |
| `VAD_SILENCE_MS` ★ | `700` | pause that ends the visitor's turn (500-800 recommended) |
| `CONNECT_TIMEOUT_S` | `6` | max wait for the Live session to connect |
| `TURN_STALL_S` | `8` | give up on a reply that stops arriving |
| `ECHO_GUARD_S` | `0.15` | extra mic mute after the skeleton speaks |
| `MOUTH_DELAY_MS` | `120` | delay of mouth levels to the body board, to line the jaw up with the speaker |

**Vision and camera**

| Variable | Default | Meaning |
|---|---|---|
| `VISION_ENABLED` | `false` | costume description on/off. Off by default because it never worked well with the ESP32 camera |
| `VISION_FRAMES` | `3` | photos per visitor |
| `VISION_INTERVAL_MS` | `500` | gap between photos |
| `VISION_DELAY_S` | `1.5` | wait after the radar trigger before the first photo |
| `VISION_GRACE_S` | `1.0` | max extra wait for the costume description after the greeting |
| `CAMERA_ROTATE_180` | `0` | camera mounted upside down |
| `PHOTOS_KEEP` | `0` | save the newest N frames to `PHOTOS_DIR`; 0 = never save |
| `PHOTOS_DIR` | `photos/` (`/data/photos` in Docker) | |

**Server and runtime files**

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | bind address for both ports |
| `PORT` | `8765` | device WebSocket |
| `ADMIN_PORT` | `8080` | admin UI |
| `DEVICE_TOKEN` | blank | bearer token; blank = no auth (LAN only) |
| `LOG_LEVEL` | `INFO` | |
| `GREETINGS_DIR`, `MODE_FILE`, `SETTINGS_FILE`, `AMBIENT_DIR` | next to the code (`/data/...` in Docker) | runtime file locations; leave unset in Docker |

**Extras**

| Variable | Default | Meaning |
|---|---|---|
| `CHATTER_INTERVAL_S` | `30` | gap between random phrases (when switched on in the admin UI) |
| `AMBIENT_FILE` | `haunted.mp3` | default background music file in `AMBIENT_DIR` (pick another in the admin UI) |
| `AMBIENT_VOLUME` | `0.5` | music volume 0-1 (voice unaffected) |
