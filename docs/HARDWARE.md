# Hardware

> This is the parts list and wiring of the original build (Halloween 2026). Links are what
> was actually bought. Most parts are generic, so equivalents work.

Two ESP32 boards, both thin WebSocket clients of the server (see `PROTOCOL.md`):

| Board | Role | Does |
|---|---|---|
| **ReSpeaker Lite** (Seeed, XMOS XU316 + XIAO ESP32-S3) | `audio` | 2-mic array with XMOS noise suppression up, speaker audio down |
| **ESP32-S3-CAM** (N16R8: 16 MB flash, 8 MB PSRAM; OV3660 camera) | `body` | radar, camera (optional costume detection), eye LEDs, optional mouth LED, jaw servo |

```
                    ┌──────────── electronics box (hardware/enclosure) ────────────┐
5 V 3 A USB-C ──► panel USB-C jack ──► + / − rails (perfboard)                      │
                    │   ├─► ESP32-S3-CAM 5V/GND pins ── radar, camera, LEDs, servo   │
                    │   ├─► ReSpeaker Lite (USB-C pigtail) ── mics, 3.5 mm out ──┐   │
                    │   └─► servo (+ caps), LED common +5 V, radar VCC           │   │
                    └────────────────────────────────────────────────────────────┼───┘
                                       USB speakers (own USB charger) ◄──────────┘
        Wi-Fi (2.4 GHz) ──► server (Gemini Live, vision, FX) over ws:// or wss://
```

## Parts list

**Electronics**

| Qty | Part | Notes |
|---|---|---|
| 1 | Seeed [**ReSpeaker Lite** 2-Mic Array Voice Kit](https://www.seeedstudio.com/ReSpeaker-Lite-Voice-Assistant-Kit-p-5929.html) (with XIAO ESP32-S3) | Needs the I2S XMOS firmware (see Firmware gotchas). Attach the Wi-Fi antenna. |
| 1 | **ESP32-S3-CAM N16R8** with OV3660 | Has two USB-C ports; flash through the one labeled **TTL**. |
| 1 | [**HLK-LD2410C** 24 GHz mmWave radar](https://a.co/d/0hV1esOd) (3-pack) | Presence + distance. Works through the plastic lid. |
| 1 | [**MG90S** metal-gear micro servo](https://a.co/d/02fCdthA) | Moves the jaw through a rigid wire. |
| 1 | [3.5 mm computer speakers](https://a.co/d/0ePMCMpM) (1Mii, with volume knob) | Plugged into the ReSpeaker's **3.5 mm jack**. Powered by **their own USB charger**, not the box supply. Any 3.5 mm speaker works; the volume knob is handy on the night. |
| 1 pack | [5 V **pre-wired** 5 mm LEDs, 8 colors, with holders](https://a.co/d/0ixjglBI) | Red for the eyes (2), plus one for the mouth if you want it (the original build never wired up the mouth LED). Pre-wired LEDs are much easier to fish through the skull. "5 V" pre-wired LEDs have the resistor built in. Avoid "3 V" ones (often no resistor) and 12 V ones (too dim). |
| 2 | **BC547** NPN transistors (or 2N2222 / 2N3904 / S8050, mind the pinout) | One for the eyes; a second only if you add the mouth LED. |
| 2 | 1 kΩ resistors | Transistor base resistors. |
| 2 | 100 µF electrolytic, ≥10 V (50 V used) | In parallel at the servo's power leads. |
| 1 | ElectroCookie half-size solderable perfboard (88.8 × 52 mm) | Power rails + transistors + headers. |
| — | JST-XH connectors, 22 AWG wire, heat shrink | 3-pin XH for the LED cable (pinout below). |
| — | M2 and M2.5 screws | ReSpeaker holes are M2 (2.3 mm); lid and ElectroCookie posts are M2.5. |

**Power**

| Qty | Part | Notes |
|---|---|---|
| 1 | [CanaKit 3.5 A Raspberry Pi 4 power supply (USB-C)](https://a.co/d/09lsC4se) | Runs the whole box (both boards, servo, radar, LEDs). The servo's current spikes are the main load. The speakers have their own charger. |
| 1 | [Panel-mount USB-C female socket → 6-pin header](https://a.co/d/0hLeTJ3o) (xiwai) | The box's power input. Only the red and black wires are used; cut the others off. It's the only connector that uses its panel nut. Pick a socket that works with USB-C chargers (has CC resistors / "PD"); "only works with USB-A" listings won't get power from a USB-C supply. |
| 1 | [USB-C male → 2-pin bare-wire pigtail](https://a.co/d/03RU1aTO) | Powers the ReSpeaker from the same + / − rails as the body board. |

**Mechanical and props**

| Qty | Part | Notes |
|---|---|---|
| 1 | [5.4 ft / 165 cm life-size posable skeleton](https://a.co/d/0d4n2F9A) | Needs a hinged jaw. |
| 1 | [12 gauge (2 mm) bendable aluminium wire](https://a.co/d/02RVcD5g) | Jaw linkage (servo arm → jaw), and also used to strap the servo to the back of the skull. |
| — | White duct tape | Holds the servo in place on the skull (white blends in). |
| — | A chair and a robe | The skeleton sat in a chair wearing a robe that hides the wires and the box. |
| 1 | 3D-printed electronics box (`hardware/enclosure`) | Optional. Cables mostly pass straight through the end-wall holes. |

## Body board pinout (ESP32-S3-CAM)

| GPIO | Connects to | Notes |
|---|---|---|
| **G1** | radar **OUT** | 3.3 V logic: high = someone present |
| **G41** | radar **TX** | UART 256000 baud: distance + energy frames (`F4 F3 F2 F1` header). Presence also works from this alone. |
| **G21** | eye transistor base (via 1 kΩ) | red eyes; PWM brightness |
| **G47** | green eyes (optional) | only used with `FAMILY_EYES_GREEN 1` |
| **G42** | mouth transistor base (via 1 kΩ) | optional; not wired in the original build |
| **G14** | servo signal (orange) | LEDC 50 Hz, 14-bit |
| G48 | on-board RGB status LED | red = no Wi-Fi, yellow = no server, green = connected, blue = radar sees someone |
| 5V / GND | + / − rails | **board is powered through its 5V pin** |

**Don't use** (taken or risky on this board): G4–G13 and G15–G18 (camera), G35–G37
(PSRAM), G38–G40 (SD card), G0/G3/G45/G46 (strapping), G19/G20 (USB), G43/G44 (UART0).

## Power

- USB-C panel jack red → **+ rail**, black → **− rail**. Star-wire everything from the
  rails (servo, body board, ReSpeaker, LED common, radar) rather than daisy-chaining.
- Both 100 µF caps go **at the servo** (+ to red, − to brown), not at the jack: they
  cover the servo's current spikes where they happen.
- The body board gets 5 V on its **5V pin**. Because of that:
  **never plug a laptop into the board's USB while box power is on**, and don't try to
  run the box from laptop USB (it can't supply the servo/radar/LEDs/ReSpeaker).
  USB is for flashing, with box power off. Day-to-day logs are on Wi-Fi:
  `nc skeleton-body.local 23`.
- ReSpeaker: powered from the rails through a USB-C pigtail.

## Radar (LD2410C)

| Radar pin | Goes to |
|---|---|
| VCC | **5 V** rail (it needs 5 V, not 3.3 V) |
| GND | − rail |
| OUT | G1 |
| TX | G41 |
| RX | not connected |

Pin order differs between LD2410C batches: **go by the printed labels**, not position.
Check with a meter that the radar's own VCC pad reads 5 V. Two radars ran hot during the
build while a jumper wasn't really making contact on VCC; verify VCC and GND before
plugging the signal wires in.

Tuning: HLKRadarTool app (Bluetooth). If it reports someone all the time, it's seeing
the box, the jaw, or a fan: lower the near gates' sensitivity. `RADAR_MAX_CM` in the body
`config.h` ignores targets past a distance (e.g. the sidewalk).

## Eye and mouth LEDs (transistor switched)

The mouth LED is optional. The firmware drives it with the voice level, but the original
build only wired the eyes (leave G42 unconnected; nothing else changes).

A GPIO only supplies ~20 mA at 3.3 V, so the LEDs run from the 5 V rail and each GPIO
just switches an NPN transistor. PWM dimming still works (the transistor follows it).

```
 5V rail ────┬───────── eye 1 red (+)
             ├───────── eye 2 red (+)
             └───────── mouth red (+)

 eye 1 black ─┬── BC547 #1 C          mouth black ── BC547 #2 C
 eye 2 black ─┘
 G21 ──[1 kΩ]──── BC547 #1 B          G42 ──[1 kΩ]──── BC547 #2 B
 GND ──────────── BC547 #1 E          GND ──────────── BC547 #2 E
```

**BC547 pinout: flat face toward you, legs down = C – B – E.** (2N2222/2N3904 are often
E – B – C. Check your part.)

3-pin JST-XH cable from the box to the skull:

| Pin | Wire | Box side | Skull side |
|---|---|---|---|
| 1 | +5 V | + rail | all LED reds joined |
| 2 | eyes − | BC547 #1 collector | both eye blacks joined |
| 3 | mouth − | BC547 #2 collector | mouth black |

Gotchas from the build:
- On perfboard, each transistor leg must be in its **own** strip. Legs sharing a strip
  short C/B/E and the LEDs stay on at full brightness.
- If the LED blacks land on the **base** (middle leg), current flows base→emitter, the
  LEDs stay on, and the GPIO can't turn them off (the LED line reads ~0.8 V).
- Bare LEDs (no built-in resistor) need about 150 Ω each at 5 V (red).
- Brightness is set live from the admin UI and saved in the board's flash.

## Jaw servo

| Servo wire | Goes to |
|---|---|
| brown/black | − rail |
| red | + rail (5 V), with the two 100 µF caps right here |
| orange | G14 |

- **Mounting (original build):** the servo is strapped to the back of the skull with the
  2 mm aluminium wire plus white duct tape.
- **Linkage (original build):** a hole drilled through the servo's stock plastic arm, and a
  piece of the 2 mm aluminium wire from there to the jaw. Bend it until the jaw closes fully at
  the closed angle. Holes farther from the shaft give more jaw travel per degree.
- `hardware/servo-horn` is a 3D-printed press-fit horn with holes for 2 mm wire at 8, 11, 14
  and 17 mm from the shaft. It was designed for this build but **not used in the end** (the
  drilled stock arm was enough). It's here in case it's useful.
- Set the angles live from the admin UI (jaw card: hold / sweep, then save). Start with
  closed and open close together, attach the linkage at the closed angle, then widen.
  If the servo buzzes at an end, it's pushing a hard stop: back that angle off.
- `JAW_RELAX_WHEN_IDLE 1` stops driving the servo when the jaw is closed and quiet
  (no idle hum).
- A whining servo during the build turned out to be a bad crimp/mirrored pin order in a
  Dupont/XH extension on the signal wire. Check extensions first.

## ReSpeaker Lite

- Mount flat side up under the lid grille (the mics are bottom-ported).
- Attach the U.FL Wi-Fi antenna and keep it against the box wall facing the router,
  away from the speaker magnet and the other board. Without it, RSSI was around -85 dBm.
- The lid grille web pressed the mute button in one revision; v7 of the box fixes it.
  If the mute LED is lit, something is pressing the button.

## Enclosure

`hardware/enclosure/skeleton_box.scad` (OpenSCAD, parametric) plus ready STLs, v7.
Print `skeleton_box_test.stl` first to check every hole with the boards. See
`hardware/enclosure/README.md` for the layout, print settings and revision history.
Outside: 98.6 × 127 × 29.5 mm plus 11 mm tie-down ears. The lid faces visitors: camera
lens through a hole, radar in a slide-in holder on the lid's underside, grille over the
ReSpeaker. End-wall holes: PWR (USB-C panel socket, with its nut), SPK, LED, AUX (3.5 mm). The SPK and LED
holes were sized for GX12 aviation connectors, but in the original build the cables just pass
straight through them.

## Firmware gotchas (hardware-related)

- **ReSpeaker I2S:** the XMOS chip is the clock **master**; the ESP32 must be I2S
  **slave**. Both driving the clock gives full-scale garbage (peak 32768). Needs the
  ReSpeaker's I2S XMOS firmware (check with `dfu-util -l`).
- **I2S output repeats its last DMA buffer** when you stop writing (static/buzz); the
  firmware uses `auto_clear` and writes silence.
- **Camera:** `fb_count 1` + `CAMERA_GRAB_WHEN_EMPTY` so each `capture` gets a fresh frame.
- **Wi-Fi:** 2.4 GHz only. Phone hotspot: iPhone "Maximize Compatibility", Android 2.4 GHz band.

## Known issues

- ReSpeaker Wi-Fi drops out more than the body board in the same spot (antenna placement
  is the first suspect). Possible firmware improvements, not yet done: join the strongest
  AP (`WIFI_ALL_CHANNEL_SCAN` + `WIFI_CONNECT_AP_BY_SIGNAL`), and make the 100 ms playback
  prebuffer configurable (~300 ms rides out Wi-Fi jitter). Check the 30 s `[stats]` line:
  disconnects point at signal, climbing `underruns` with good RSSI point at buffering.
- On the original build the radar OUT → G1 connection never read high; presence runs from
  the TX data instead (`RADAR_PRESENCE_SOURCE 2` uses either).
