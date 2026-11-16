"""Tiny HTTP admin API + static page for live settings (voice/FX/timing/mode).
Runs in the same asyncio loop as the websocket server, on its own port
(ADMIN_PORT, default 8080) — see server.py's Server.run().
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .config import Config
from .log_ring import RING
from .modes import VALID as MODE_VALID
from .modes import current_mode, requested_mode
from .settings_store import ValidationError, clear_overrides, save_overrides, schema_json, values_json

log = logging.getLogger("skeleton.admin")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@web.middleware
async def same_origin_only(request: web.Request, handler):
    """Block cross-site requests: without this, any web page open on a phone on the same
    network could POST to /api/say etc. Browsers send Origin on cross-origin requests;
    curl and scripts send none and are allowed (the admin UI has no login anyway)."""
    origin = request.headers.get("Origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None:
        if urlsplit(origin).netloc.lower() != request.host.lower():
            log.warning("blocked cross-site %s %s from origin %s", request.method, request.path, origin)
            return web.json_response({"error": "cross-site request blocked"}, status=403)
    return await handler(request)


def build_app(cfg: Config, get_hub) -> web.Application:
    app = web.Application(middlewares=[same_origin_only])

    async def index(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def get_settings(request: web.Request) -> web.Response:
        return web.json_response({"values": values_json(cfg), "schema": schema_json()})

    async def post_settings(request: web.Request) -> web.Response:
        try:
            patch = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        if not isinstance(patch, dict):
            return web.json_response({"error": "expected a JSON object"}, status=400)
        try:
            save_overrides(cfg, patch)
        except ValidationError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"values": values_json(cfg), "schema": schema_json()})

    async def reset_settings(request: web.Request) -> web.Response:
        clear_overrides(cfg)
        return web.json_response({"values": values_json(cfg), "schema": schema_json()})

    async def get_mode(request: web.Request) -> web.Response:
        return web.json_response({"requested": requested_mode(cfg), "current": current_mode(cfg)})

    async def post_mode(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        mode = body.get("mode")
        if mode not in MODE_VALID:
            return web.json_response({"error": f"mode must be one of {MODE_VALID}"}, status=400)
        cfg.mode_file.write_text(mode + "\n")
        return web.json_response({"requested": requested_mode(cfg), "current": current_mode(cfg)})

    async def get_status(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"ready": False})
        return web.json_response({
            "ready": True,
            "mode": {"requested": requested_mode(cfg), "current": hub.mode},
            "brain": "gemini" if cfg.use_gemini else "echo",
            "devices": {
                "audio": hub.audio.name if hub.audio else None,
                "body": hub.body.name if hub.body else None,
            },
            "conversation_active": bool(hub.conv_task and not hub.conv_task.done()),
            "announcing": hub.announcing,
            "ambient": {"enabled": hub.ambient.enabled, "playing": hub.ambient.playing},
            "sensor_enabled": hub.sensor_enabled,
            "chatter": {"enabled": hub.chatter.enabled, "speaking": hub.chatter.speaking},
            "cooldown_remaining_s": max(0.0, hub.cooldown_until - time.monotonic()),
        })

    async def get_log(request: web.Request) -> web.Response:
        after = int(request.query.get("after", 0))
        lines = RING.tail(after=after)
        return web.json_response({"lines": [{"id": ln.id, "text": ln.text} for ln in lines]})

    async def post_presence(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        present = bool(body.get("present"))
        hub.set_presence(present, force=True)  # aux clients hear manual clicks even with no body/audio
        if present:
            hub.start_conversation()  # logs "trigger ignored" if nothing can act on it
        else:
            hub.mark_left()
        return web.json_response({"ok": True})

    async def post_sensor(request: web.Request) -> web.Response:
        """Turn the body's motion sensor on/off. In memory only (on after a restart).
        While off, the body's "someone arrived" reports are ignored; the manual
        buttons below still work."""
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        enabled = body.get("enabled") if isinstance(body, dict) else None
        if not isinstance(enabled, bool):
            return web.json_response({"error": "enabled must be true or false"}, status=400)
        hub.sensor_enabled = enabled
        log.info("motion sensor %s from the admin UI", "enabled" if enabled else "DISABLED")
        return web.json_response({"enabled": enabled})

    def _chatter_json(hub) -> dict:
        c = hub.chatter
        return {"enabled": c.enabled, "speaking": c.speaking, "interval_s": c.interval_s,
                "error": c.error, "mode": hub.mode, "phrases": c.listing(hub.mode)}

    async def get_chatter(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        return web.json_response(_chatter_json(hub))

    async def post_chatter(request: web.Request) -> web.Response:
        """Random phrases on/off (in memory only; off after a restart)."""
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        enabled = body.get("enabled") if isinstance(body, dict) else None
        if not isinstance(enabled, bool):
            return web.json_response({"error": "enabled must be true or false"}, status=400)
        hub.chatter.set_enabled(enabled)
        log.info("random phrases %s from the admin UI", "ON" if enabled else "off")
        return web.json_response(_chatter_json(hub))

    async def post_chatter_phrase(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            body = await request.json()
            hub.chatter.add(body.get("text") if isinstance(body, dict) else None)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(_chatter_json(hub))

    async def post_say(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        text = (body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text is required"}, status=400)
        try:
            hub.start_announcement(text)
        except RuntimeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"ok": True})

    def _ambient_json(hub) -> dict:
        a = hub.ambient
        return {"enabled": a.enabled, "playing": a.playing, "file": a.file, "files": a.files(),
                "volume": a.volume, "error": a.error}

    async def get_ambient(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        return web.json_response(_ambient_json(hub))

    async def post_ambient(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            enabled = body.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                raise ValueError("enabled must be true or false")
            volume = body.get("volume")
            if volume is not None and (isinstance(volume, bool) or not isinstance(volume, (int, float))
                                       or not 0 <= volume <= 1):
                raise ValueError("volume must be a number from 0 to 1")
            file = body.get("file")
            if file is not None and file not in hub.ambient.files():
                raise ValueError("unknown file")
            hub.ambient.configure(enabled=enabled, file=file, volume=volume)
            patch = {}
            if file is not None:
                patch["ambient_file"] = file
            if volume is not None:
                patch["ambient_volume"] = float(volume)
            if patch:
                save_overrides(cfg, patch)
        except ValueError as e:  # includes ValidationError
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(_ambient_json(hub))

    async def get_photos(request: web.Request) -> web.Response:
        hub = get_hub()
        photos = list(hub.recent_photos) if hub else []
        return web.json_response({"photos": [{"ts": ts, "size": len(b)} for ts, b in photos]})

    async def get_photo(request: web.Request) -> web.Response:
        hub = get_hub()
        photos = list(hub.recent_photos) if hub else []
        try:
            ts, jpeg = photos[int(request.match_info["idx"])]
        except (ValueError, IndexError):
            return web.Response(status=404)
        return web.Response(body=jpeg, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def post_capture(request: web.Request) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        if hub.body is None:
            return web.json_response({"error": "body device not connected"}, status=400)
        await hub.send_body_json({"type": "capture", "count": 1, "interval_ms": 0})
        return web.json_response({"ok": True})

    def _angle(body: dict, key: str) -> float | None:
        v = body.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 180:
            raise ValueError(f"{key} must be a number from 0 to 180")
        return float(v)

    async def _jaw(msg: dict) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            jaw = await hub.jaw_request(msg)
        except RuntimeError as e:
            return web.json_response({"error": str(e), "jaw": hub.jaw}, status=400)
        return web.json_response({"jaw": jaw})

    async def get_jaw(request: web.Request) -> web.Response:
        return await _jaw({"type": "jaw_get"})

    async def post_jaw_config(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            msg: dict = {"type": "jaw_config", "save": bool(body.get("save", True))}
            if body.get("reset"):
                msg["reset"] = True
            else:
                for key in ("closed", "open"):
                    v = _angle(body, key)
                    if v is not None:
                        msg[key] = v
                if "closed" not in msg and "open" not in msg:
                    raise ValueError("give closed and/or open (or reset)")
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        return await _jaw(msg)

    async def post_jaw_test(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            action = body.get("action")
            if action not in ("sweep", "hold", "open", "closed"):
                raise ValueError("action must be sweep, hold, open or closed")
            msg: dict = {"type": "jaw_test", "action": action}
            if action == "sweep":
                count = body.get("count", 3)
                if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
                    raise ValueError("count must be a whole number from 1 to 20")
                msg["count"] = count
            else:
                ms = body.get("ms", 3000)
                if isinstance(ms, bool) or not isinstance(ms, int) or not 100 <= ms <= 10000:
                    raise ValueError("ms must be a whole number from 100 to 10000")
                msg["ms"] = ms
            if action == "hold":
                deg = _angle(body, "deg")
                if deg is None:
                    raise ValueError("hold needs deg")
                msg["deg"] = deg
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        return await _jaw(msg)

    def _level(body: dict, key: str, default: float | None = None) -> float | None:
        v = body.get(key, default)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            raise ValueError(f"{key} must be a number from 0 to 1")
        return float(v)

    async def _leds(msg: dict) -> web.Response:
        hub = get_hub()
        if hub is None:
            return web.json_response({"error": "server not ready"}, status=503)
        try:
            leds = await hub.led_request(msg)
        except RuntimeError as e:
            return web.json_response({"error": str(e), "leds": hub.leds}, status=400)
        return web.json_response({"leds": leds})

    async def get_leds(request: web.Request) -> web.Response:
        return await _leds({"type": "led_get"})

    async def post_leds_config(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            msg: dict = {"type": "led_config", "save": bool(body.get("save", True))}
            if body.get("reset"):
                msg["reset"] = True
            else:
                for key in ("eyes", "mouth"):
                    v = _level(body, key)
                    if v is not None:
                        msg[key] = v
                if "eyes" not in msg and "mouth" not in msg:
                    raise ValueError("give eyes and/or mouth (or reset)")
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        return await _leds(msg)

    async def post_leds_test(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            if body.get("action") == "stop":
                msg: dict = {"type": "led_test", "action": "stop"}
            else:
                target = body.get("target", "both")
                if target not in ("eyes", "mouth", "both"):
                    raise ValueError("target must be eyes, mouth or both")
                ms = body.get("ms", 3000)
                if isinstance(ms, bool) or not isinstance(ms, int) or not 100 <= ms <= 60000:
                    raise ValueError("ms must be a whole number from 100 to 60000")
                msg = {"type": "led_test", "target": target, "level": _level(body, "level", 1.0), "ms": ms}
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        return await _leds(msg)

    app.router.add_get("/", index)
    app.router.add_get("/api/leds", get_leds)
    app.router.add_post("/api/leds/config", post_leds_config)
    app.router.add_post("/api/leds/test", post_leds_test)
    app.router.add_get("/api/jaw", get_jaw)
    app.router.add_post("/api/jaw/config", post_jaw_config)
    app.router.add_post("/api/jaw/test", post_jaw_test)
    app.router.add_get("/api/ambient", get_ambient)
    app.router.add_post("/api/ambient", post_ambient)
    app.router.add_get("/api/photos", get_photos)
    app.router.add_get("/api/photos/{idx}", get_photo)
    app.router.add_post("/api/capture", post_capture)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", post_settings)
    app.router.add_post("/api/settings/reset", reset_settings)
    app.router.add_get("/api/mode", get_mode)
    app.router.add_post("/api/mode", post_mode)
    app.router.add_get("/api/status", get_status)
    app.router.add_get("/api/log", get_log)
    app.router.add_post("/api/presence", post_presence)
    app.router.add_post("/api/sensor", post_sensor)
    app.router.add_get("/api/chatter", get_chatter)
    app.router.add_post("/api/chatter", post_chatter)
    app.router.add_post("/api/chatter/phrases", post_chatter_phrase)
    app.router.add_post("/api/say", post_say)
    return app


async def run_admin(cfg: Config, get_hub) -> None:
    app = build_app(cfg, get_hub)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, cfg.host, cfg.admin_port)
    await site.start()
    log.info("admin UI on http://%s:%d", cfg.host, cfg.admin_port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
