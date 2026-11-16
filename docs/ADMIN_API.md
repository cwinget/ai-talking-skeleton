# Admin HTTP API

Everything the admin UI does goes through these JSON endpoints on `ADMIN_PORT` (8080). They are
defined in `skeleton/admin.py`. **There is no authentication.** Anyone who can reach the port can
make the skeleton talk and see camera frames. Keep it on your LAN or behind a password (see
[DEPLOY.md](DEPLOY.md#behind-traefik)).

All `POST` bodies are JSON. Errors come back as `{"error": "..."}` with status 400. Before the
server has finished starting, most endpoints return 503 (`/api/status` returns `{"ready": false}`).

## Status and log

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/status` | | devices, persona mode, brain (`gemini`/`echo`), conversation/cooldown state, music, chatter, sensor |
| GET | `/api/log?after=<id>` | | `{"lines":[{"id","text"}]}`: recent server log lines after `id` |

## Persona and settings

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/mode` | | `{"requested","current"}` |
| POST | `/api/mode` | `{"mode":"auto"\|"family"\|"scary"}` | writes `mode.txt` |
| GET | `/api/settings` | | current values + schema (labels, ranges) |
| POST | `/api/settings` | `{"voice":"Puck","fx_pitch":-5,...}` | validated, saved in `settings.json`, applies from the next conversation. Keys: see `SCHEMA` in `skeleton/settings_store.py` |
| POST | `/api/settings/reset` | | clears all overrides (back to `.env`) |

## Visitors and speech

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/presence` | `{"present":true\|false}` | same as the radar: starts a conversation / marks the visitor as gone. Also forwarded to `aux` clients |
| POST | `/api/sensor` | `{"enabled":true\|false}` | ignore the radar while off (in memory; on after restart) |
| POST | `/api/say` | `{"text":"..."}` | speak this text verbatim in the current voice. Not sent to the model. Refused during a conversation |
| GET | `/api/chatter` | | random-phrases state and phrase list |
| POST | `/api/chatter` | `{"enabled":true\|false}` | random phrases on/off (off after restart) |
| POST | `/api/chatter/phrases` | `{"text":"..."}` | add a phrase for the current mode |
| GET | `/api/ambient` | | music state, files, volume |
| POST | `/api/ambient` | `{"enabled":bool,"file":"x.mp3","volume":0-1}` (all optional) | file and volume are persisted |

## Camera

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/photos` | | `{"photos":[{"ts","size"}]}`: last 8 frames, in memory only |
| GET | `/api/photos/{idx}` | | JPEG |
| POST | `/api/capture` | | ask the body board for one test photo |

## Jaw and LEDs (body board)

These are forwarded to the body board, and the server waits up to 3 s for its reply.
Responses: `{"jaw":{"closed","open","saved"}}` / `{"leds":{"eyes","mouth","saved"}}`.

| Method | Path | Body |
|---|---|---|
| GET | `/api/jaw` | |
| POST | `/api/jaw/config` | `{"closed":0-180,"open":0-180,"save":true}` or `{"reset":true}` |
| POST | `/api/jaw/test` | `{"action":"sweep","count":1-20}`, `{"action":"hold","deg":0-180,"ms":100-10000}`, `{"action":"open"\|"closed","ms":...}` |
| GET | `/api/leds` | |
| POST | `/api/leds/config` | `{"eyes":0-1,"mouth":0-1,"save":true}` or `{"reset":true}` |
| POST | `/api/leds/test` | `{"target":"eyes"\|"mouth"\|"both","level":0-1,"ms":100-60000}` or `{"action":"stop"}` |

Example:

```bash
curl -s localhost:8080/api/status | python -m json.tool
curl -s -X POST localhost:8080/api/say -H 'Content-Type: application/json' -d '{"text":"Boo!"}'
```
