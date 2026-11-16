# Tuning

Most of this can be done from the **admin UI** (port 8080) while the server runs. Changes
there apply from the next conversation. Paths below are relative to where runtime files live:
the repo folder when running with Python, `data/` when running in Docker (see
[DEPLOY.md](DEPLOY.md#the-data-volume)).

## Persona: family vs. scary

- **family**: goofy, punny, warm. For little kids.
- **scary**: slow, ominous, creepy by suggestion. It follows the same hard rules (no gore, no
  real threats, nothing personal), and it **drops the act and turns gentle** if a visitor
  sounds young or frightened, or asks it to stop.

With `PERSONA_MODE=auto` it's family until `SCARY_START` (20:30) and scary until `SCARY_END`
(05:00). The mode is picked when each visitor arrives.

To override it instantly, without a restart, use the admin UI's **Auto / Family / Scary**
buttons, or write the file directly:

```bash
echo scary > mode.txt     # family / scary / auto
rm mode.txt               # back to PERSONA_MODE and the clock
```

To test the clock switch: `python -m skeleton.server --pretend-time 21:15`, or force a mode with
`--mode scary` (`mode.txt` still wins over both).

The personalities themselves are in `skeleton/prompts.py`: `FAMILY_PERSONA`, `SCARY_PERSONA`,
the shared `COSTUME_RULES` and `SAFETY_RULES`, the nudge/goodbye stage directions, and
`VISION_PROMPT`. Edit the safety rules carefully: real kids will talk to this.

## Voice

Set `VOICE` (admin UI: Voice & Persona). Audition voices in AI Studio's Live playground
(<https://aistudio.google.com/live>). The default is Charon; deeper or rougher voices work well.
Scary mode can use its own voice (`SCARY_VOICE`). Blank means the same as family.

After changing a voice, **regenerate the greetings** so they match:

```bash
python -m skeleton.greetings                 # all modes
python -m skeleton.greetings --mode scary    # one mode
```

Then restart the server. In Docker, prefix these with `docker compose exec skeleton-brain`.

## Greetings

Greetings are pre-generated so the skeleton can talk instantly while the Live session connects
and the costume photos are analysed. Each mode has its own `greetings/<mode>/lines.txt`, one
line per greeting. `#` lines are ignored. The file is created from the defaults in `skeleton/prompts.py` the
first time greetings are generated (first start with an API key). Then:

```bash
python -m skeleton.greetings --mode family            # regenerate a mode
python -m skeleton.greetings --mode family --only 2 4 # just lines 2 and 4
```

Silence is trimmed automatically. You get a warning if the transcript doesn't match the
script, which usually means a mumbled or cut-off take; rerun that line. Aim for under about 6 s
per greeting: the greeting's length is also the time budget for the costume description
(`VISION_GRACE_S` adds a bit more).

## Voice effects

Preview without a conversation (needs `requirements.txt` for audio playback):

```bash
python -m skeleton.fx_preview greetings/family/greet_01.wav --compare
python -m skeleton.fx_preview greetings/family/greet_01.wav --pitch -6 --reverb 0.45 --drive 8
python -m skeleton.fx_preview greetings/family/greet_01.wav --pitch -6 --out test.wav --no-play
```

Put the values you like in the admin UI or `.env` (`FX_PITCH_SEMITONES`, `FX_REVERB`,
`FX_DRIVE_DB`, `FX_GAIN_DB`, and the `SCARY_FX_*` variants). The pitch shifter is a custom
low-latency one (~25 ms). pedalboard's built-in PitchShift sounds cleaner but buffers about
1.1 s when streaming, which would add a second of silence before every reply. The slight
warble at big shifts is part of the charm.

## Conversation timing

All of these are in the admin UI's Timing group:

| Setting | Effect |
|---|---|
| `VAD_SILENCE_MS` | how long a pause ends the visitor's turn. Lower = snappier but interrupts slow talkers. 500-800 |
| `SILENCE_TIMEOUT_S` | silence before one nudge ("still there?"), then goodbye |
| `MAX_TURNS`, `MAX_CONVERSATION_S` | then it says goodbye |
| `COOLDOWN_S` | radar ignored after a conversation, so the same group doesn't restart it |

If the skeleton responds to itself, raise `ECHO_GUARD_S` in `.env` (e.g. 0.4). The server
ignores the mic while the skeleton talks, until the audio board confirms playback finished,
plus this guard.

## Jaw and LEDs

These are calibrated live from the admin UI. Values are saved in the **body board's flash**,
not on the server, and override the `config.h` defaults.

**Jaw calibration card**

1. Before attaching the linkage, set closed and open close together (e.g. 90 / 100) and
   "Save to board".
2. Attach the horn/linkage with the servo at the closed angle.
3. Use **Hold** to try angles. Widen open a few degrees at a time and check with
   **Sweep ×5**.
4. If the jaw opens when it should close, swap the two numbers. If the servo buzzes at one
   end, it's pushing a hard stop: back that angle off.
5. **Reset to firmware defaults** erases the saved values.

**Eye & mouth brightness card**: do it in the dark with the skull assembled. "Hold at this
level (10 s)" shows a fixed brightness, and **Save** stores it. It's a maximum: the idle
breathing and the voice-driven glow are scaled under it.

**Jaw timing**: if the jaw moves before the sound, raise `MOUTH_DELAY_MS` in `.env`. If it
lags, lower it. Default 120 ms.

## Random phrases

The admin UI's **Random phrases** toggle makes the skeleton say a funny (family) or spooky
(scary) phrase every `CHATTER_INTERVAL_S` (30 s), whether or not anyone is there. A visitor
arriving interrupts it. Phrases are in `greetings/<mode>/phrases/lines.txt`, and you can add
more from the UI. Missing audio is generated in the background at startup (needs an API key;
without one a tone plays). Always off after a restart.

## Background music

Put mp3s in the ambient folder: `data/ambient/` in Docker, `ambient/` next to the code
otherwise (`AMBIENT_DIR`). **None is included**; use music you have the rights to. (The original build looped a track
from Disney's Haunted Mansion, which can't be redistributed. Hence the default file name
`haunted.mp3`.) In the
admin UI's **Background audio** card, pick a file, set the volume and switch it on. It loops
while nobody is talking, fades out (~1.5 s) when someone arrives or you use "Play" (say this
out loud), and comes back after the conversation and cooldown. It's always off after a
restart. The volume only affects the music, not the skeleton's voice.

## Camera

- Upside-down photos: `CAMERA_ROTATE_180=1` on the server, or `CAM_VFLIP` / `CAM_HMIRROR` in
  the body `config.h`.
- **Take test photo** in the admin UI's Camera card shows what the skeleton sees. Do this
  while aiming the box.
- `VISION_DELAY_S` waits after the radar trigger so the visitor has stepped into view.
