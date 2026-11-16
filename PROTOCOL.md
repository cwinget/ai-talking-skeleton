# Device ↔ Server Protocol

Devices connect to `ws://<server>:8765/` (LAN) or `wss://<your-ws-host>/` (through a TLS
reverse proxy such as Traefik; see `docs/DEPLOY.md`).
When the server has `DEVICE_TOKEN` set, the HTTP upgrade request must carry
`Authorization: Bearer <DEVICE_TOKEN>`; otherwise the server answers `401` and
no WebSocket is opened. The **first message must be `hello`**
with a `role`:

| role | device | does |
|---|---|---|
| `audio` | ReSpeaker Lite (`firmware/audio`) | mic up, speaker down, `playback_done` |
| `body` | ESP32-S3-CAM (`firmware/body`) | `presence`, `image`, receives `capture`, mouth levels, `state` |
| `both` | Mac simulator default; also the role used if `role` is omitted | everything |
| `aux` | anything that wants to react to visitors (e.g. a fog machine or porch light controller) | receives `presence` only; see below |

The server keeps one device per role; a new device for a role replaces the old
one. Conversations need an audio device; triggers come from whichever device
sends `presence`.

Audio everywhere is **signed 16-bit little-endian, mono, 16 kHz**.

## Device → Server

### Binary: microphone audio
Raw PCM, no header. Send continuously in 20 ms chunks (640 bytes). The server
discards mic audio whenever the skeleton isn't listening, so the device doesn't
need to know the conversation state.

### Text (JSON)
| type | fields | when |
|---|---|---|
| `hello` | `role`, `device`, `rate` | first message after connecting (required) |
| `presence` | `present: true/false` | radar state changes. `true` starts a conversation (ignored during cooldown or an active one). `false` ends it gracefully. |
| `trigger` | — | same as `presence: true` (used by tests) |
| `image` | `seq`, `jpeg_b64` | reply to `capture`: one message per frame, JPEG ≤ ~768 px wide |
| `jaw_config` | `closed`, `open` (deg, floats), `saved` (bool: values are in flash) | reply to any `jaw_config` / `jaw_test` / `jaw_get` from the server |
| `led_config` | `eyes`, `mouth` (0-1 floats), `saved` (bool: values are in flash) | reply to any `led_config` / `led_test` / `led_get` |
| `playback_done` | `id` | the speaker has actually finished playing utterance `id` (buffer empty + output latency) |

## Server → Device

### Binary: speaker audio + mouth level
```
byte 0      0x01 (audio frame)
byte 1      env: mouth/LED level 0..255 for this exact chunk
bytes 2..   PCM, 320 samples (20 ms, 640 bytes)
```
Play frames in order. Apply `env` to the LEDs/jaw **when that frame starts
playing**, not when it arrives; that keeps the mouth in sync with the voice.
The server sends at real-time pace with ~300 ms lead, so a 0.5–1 s jitter
buffer is plenty.

### Binary: mouth level (body device only)
```
byte 0      0x02 (mouth frame)
byte 1      env 0..255
```
Sent 50×/s while the skeleton talks, timed to arrive when the matching audio
plays on the audio device (plus `MOUTH_DELAY_MS`), so the body applies it
**on arrival**. A final `0` closes the mouth. A `both` device doesn't get these;
it uses the `env` byte inside each audio frame instead.

### Text (JSON)
| type | fields | device action |
|---|---|---|
| `play_start` | `id` | new utterance begins (optional to act on) |
| `play_end` | `id` | no more frames for `id`. When the buffer drains, send `playback_done` with the same `id`. **Required**: the server won't reopen the mic until it gets this (3 s timeout fallback). |
| `capture` | `count`, `interval_ms` | take `count` photos, `interval_ms` apart, send each as `image` |
| `state` | `state`: `greeting` / `listening` / `speaking` / `idle`, `mode` | optional: idle eye glow, "listening" glow, etc. |
| `mode` | `mode`: `family` / `scary` | body: persona changed (sent on connect and whenever it changes); e.g. eye color |
| `jaw_config` | `closed`, `open` (deg 0-180, each optional), `save` (bool, default true), `reset` (bool, optional) | body only. Sets the jaw angles, saves to flash if `save`, sweeps once to show the range. `reset: true` erases saved values and reverts to the `config.h` defaults. Replies `jaw_config`. |
| `jaw_test` | `action`: `sweep` / `hold` / `open` / `closed`; `count` (sweep, 1-20), `deg` (hold), `ms` (hold/open/closed, default 3000) | body only. A temporary motion that overrides the voice-driven jaw, then returns to normal. Replies `jaw_config`. |
| `jaw_get` | — | body only. Replies `jaw_config`. |
| `led_config` | `eyes` (0-1, optional), `mouth` (0-1, optional), `save` (bool, default true), `reset` (bool, optional) | body only. Sets the max-brightness scale (perceptual; the board applies a square curve) multiplied onto the normal animation, saves to flash if `save`, shows the new max on the changed LEDs for 1.5 s. `reset: true` erases saved values and reverts to the `config.h` defaults. Replies `led_config`. |
| `led_test` | `target`: `eyes` / `mouth` / `both` (default `both`); `level` (0-1, default 1); `ms` (default 3000, 100-60000), or `action: "stop"` | body only. Holds the target LEDs at an absolute `level` (not scaled) for `ms`, overriding the animation, then returns to normal. `stop` ends a running test. Replies `led_config`. |
| `led_get` | — | body only. Replies `led_config`. |
| `stop` | — | flush the playback buffer immediately |
| `volume` | `gain` (1.0 = unchanged) | audio device software output gain |

Jaw commands are sent from the admin UI (`/api/jaw`, `/api/jaw/config`,
`/api/jaw/test`), validated, and forwarded to the body device. The admin API waits
up to 3 s for the body's `jaw_config` reply. They are allowed during a conversation
(a warning is logged). A `both` device counts as a body and may ignore them.

LED commands work like the jaw ones: sent from the admin UI (`/api/leds`,
`/api/leds/config`, `/api/leds/test`), validated (levels 0-1, `ms` 100-60000) and forwarded
to the body, with up to 3 s wait for its `led_config` reply. Allowed mid-conversation
(a warning is logged). The server logs each reply: `leds: eyes 0.35 mouth 0.60 (saved)`.

Routing: `play_start`/`play_end`/audio frames go to the audio device; `capture`
and mouth frames go to the body device; `state` goes to both.

## `aux` role: presence listeners
An `aux` client says `{"type":"hello","role":"aux","device":"<name>"}` and then only
receives `{"type":"presence","present":true|false}`: once right after connecting (the
current state) and again whenever presence changes, including the admin UI's "Someone
arrived" / "Someone left" buttons, and `false` if the body board disconnects while someone is
present. While the motion sensor is switched off in the admin UI, radar reports are not
forwarded. Anything an aux client sends is ignored, so it can never start a conversation or
reach the audio/body boards. Any number of aux clients may connect; a new connection with the
same `device` name and IP replaces the old one. Sends to aux clients time out after 2 s and a
dead client is dropped. Aux clients use the same `DEVICE_TOKEN` as the boards.

## Typical sequence
```
dev: presence {present:true}
srv: state greeting ; capture {count:3} ; play_start 1 ; [audio frames...] ; play_end 1
dev: image x3 ; ... playback_done 1
srv: state listening                 (mic now forwarded to the model)
dev: [mic frames...]                 (visitor talks; model's VAD detects the end)
srv: state speaking ; play_start 2 ; [audio...] ; play_end 2
dev: playback_done 2
srv: state listening ... (repeat) ... goodbye utterance ... state idle
```

## Hardware notes
- ReSpeaker Lite: the XMOS chip is the I2S clock **master**; the ESP32 must be
  I2S **slave** (if both drive the clock you get full-scale garbage, peak 32768).
  Audio is 16 kHz, 32-bit stereo slots, 16-bit samples in the top half; the left
  channel is the processed (noise-suppressed) voice.
- The ESP32 I2S output repeats its last DMA buffers if you stop writing; use
  `auto_clear` and keep writing silence.
