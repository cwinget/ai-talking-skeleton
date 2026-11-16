"""Skeleton server. Devices connect over WebSocket (PROTOCOL.md) and announce a
role: "audio" (mic + speaker, e.g. the ReSpeaker), "body" (radar, camera, LEDs,
jaw), or "both" (the Mac simulator by default). The server routes between them.

    python -m skeleton.server
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import hmac
import io
import json
import logging
import random
import time
from dataclasses import replace
from http import HTTPStatus

import numpy as np
from PIL import Image
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response
from websockets.exceptions import ConnectionClosed

from . import log_ring
from . import protocol as P
from .admin import run_admin
from .ambient import Ambient
from .brain import echo_tone, make_brain
from .chatter import Chatter
from .config import Config, load_config
from .fx import Framer, VoiceFX, pcm16_to_float
from .greetings import Greeting, ensure_greetings, synthesize_line
from .modes import _hhmm, cfg_for_mode, current_mode, requested_mode
from .prompts import MODES, persona_prompt, scene_note
from .settings_store import effective as effective_settings
from .vision import Vision

log = logging.getLogger("skeleton")


class Player:
    """Streams one utterance to the device at real-time pace, then waits for the
    device to report that playback has actually finished."""

    LEAD_S = 0.3  # how far ahead of real time we let the device buffer

    def __init__(self, dev: "Hub"):
        self.dev = dev
        self.framer = Framer()
        self.t0: float | None = None
        self.sent = 0
        self.play_id = 0

    async def begin(self) -> None:
        self.play_id = self.dev.new_play_id()
        await self.dev.send_audio_json({"type": "play_start", "id": self.play_id})

    async def feed(self, samples16k: np.ndarray) -> None:
        for env, pcm in self.framer.push(samples16k):
            await self._send(env, pcm)

    async def _send(self, env: int, pcm: bytes) -> None:
        now = time.monotonic()
        if self.t0 is None:
            self.t0 = now
        ahead = self.sent / P.DEVICE_RATE - (now - self.t0)
        if ahead < 0:  # source fell behind real time; re-anchor so we keep a lead
            self.t0 = now - self.sent / P.DEVICE_RATE
        elif ahead > self.LEAD_S:
            await asyncio.sleep(ahead - self.LEAD_S)
        await self.dev.send_audio_bytes(P.pack_audio(env, pcm))
        # Mouth for a separate body device: due when this frame should be playing.
        self.dev.schedule_mouth(self.t0 + self.sent / P.DEVICE_RATE, env)
        self.sent += P.FRAME_SAMPLES

    async def end(self) -> None:
        for env, pcm in self.framer.flush():
            await self._send(env, pcm)
        await self.dev.send_audio_json({"type": "play_end", "id": self.play_id})
        if self.t0 is not None:
            self.dev.schedule_mouth(self.t0 + self.sent / P.DEVICE_RATE, 0)  # close the mouth
        buffered = 0.0
        if self.t0 is not None:
            buffered = max(0.0, self.sent / P.DEVICE_RATE - (time.monotonic() - self.t0))
        await self.dev.wait_playback_done(self.play_id, buffered + 3.0)
        await asyncio.sleep(self.dev.cfg.echo_guard_s)


def client_ip(ws: ServerConnection) -> str:
    """Real client IP: first X-Forwarded-For hop (set by Traefik), else the TCP peer."""
    try:
        xff = ws.request.headers.get("X-Forwarded-For")
    except AttributeError:
        xff = None
    if xff:
        return xff.split(",")[0].strip()
    return ws.remote_address[0]


def rotate_jpeg_180(jpeg: bytes) -> bytes:
    """Return the JPEG turned upside down (for a camera mounted inverted)."""
    out = io.BytesIO()
    with Image.open(io.BytesIO(jpeg)) as img:
        img.transpose(Image.Transpose.ROTATE_180).save(out, "JPEG", quality=90)
    return out.getvalue()


def make_auth_check(token: str):
    """`process_request` hook for the device WebSocket: reject the HTTP upgrade with
    401 unless the client sent `Authorization: Bearer <token>`. An empty token
    disables the check (LAN / simulator use)."""
    expected = token.encode()

    def check(ws: ServerConnection, request: Request) -> Response | None:
        if not expected:
            return None
        auth = request.headers.get("Authorization", "")
        scheme, _, given = auth.partition(" ")
        if scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), expected):
            return None
        xff = request.headers.get("X-Forwarded-For")
        ip = xff.split(",")[0].strip() if xff else (ws.remote_address or ("?",))[0]
        log.warning("rejected device connection from %s: %s", ip,
                    "bad token" if auth else "no token")
        resp = ws.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
        resp.headers["WWW-Authenticate"] = "Bearer"
        return resp

    return check


class Conn:
    """One device connection and the role(s) it serves."""

    def __init__(self, ws: ServerConnection, role: str, name: str):
        self.ws = ws
        self.role = role  # "audio" | "body" | "both" | "aux" (presence listener only)
        self.name = name
        self.lock = asyncio.Lock()

    @property
    def does_audio(self) -> bool:
        return self.role in ("audio", "both")

    @property
    def does_body(self) -> bool:
        return self.role in ("body", "both")

    async def send(self, data) -> None:
        async with self.lock:
            await self.ws.send(data)


class Hub:
    """Conversation state + routing. Lives for the whole server run; devices
    come and go underneath it."""

    def __init__(self, cfg: Config, greetings: dict[str, list[Greeting]], vision: Vision):
        self.audio: Conn | None = None
        self.body: Conn | None = None
        self.mouth_q: asyncio.Queue[tuple[float, int]] = asyncio.Queue()
        self.mouth_task: asyncio.Task | None = None
        self.env_cfg = cfg  # pristine .env-loaded config; admin overrides never change this
        self.cfg = cfg      # env_cfg + current admin overrides; refreshed each conversation
        self.greetings = greetings
        self.mode = current_mode(cfg)
        self.active_cfg = cfg  # cfg with the current mode's voice/FX overrides
        self.mode_task: asyncio.Task | None = None
        self._announced: tuple[int, str] | None = None  # (id(body), mode) last sent
        self.vision = vision
        self.mic_mode = "drop"  # "drop" or "forward"
        self.mic_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)
        self.image_q: asyncio.Queue[bytes] = asyncio.Queue()
        self.recent_photos: collections.deque[tuple[float, bytes]] = collections.deque(maxlen=8)  # admin preview
        self._play_id = 0
        self._waiters: dict[int, asyncio.Event] = {}
        self.conv_task: asyncio.Task | None = None
        self.cooldown_until = 0.0
        self.leave_requested = False
        self.brain = None  # the live Brain for the current conversation, or None
        self.announcing = False  # admin "speak this out loud" in progress
        self.jaw: dict | None = None  # last jaw_config the body reported
        self._jaw_waiters: list[asyncio.Future] = []
        self.leds: dict | None = None  # last led_config the body reported
        self._led_waiters: list[asyncio.Future] = []
        self.ambient = Ambient(self)  # idle background music; never plays over speech
        self.chatter = Chatter(self)  # random phrases on a timer; admin UI toggle
        self.aux: list[Conn] = []  # presence-only listeners (e.g. a pumpkin); never affect the skeleton
        self.present = False       # last presence state reported by the radar
        self.sensor_enabled = True  # admin UI toggle; in memory only, so always on after a restart
        self._aux_tasks: set[asyncio.Task] = set()

    # ---------- devices ----------
    def attach(self, conn: Conn) -> list[Conn]:
        """Register a device; returns connections it replaces (caller closes them)."""
        replaced = []
        if conn.does_audio:
            if self.audio and self.audio is not conn:
                replaced.append(self.audio)
            self.audio = conn
        if conn.does_body:
            if self.body and self.body is not conn:
                replaced.append(self.body)
            self.body = conn
        # A replaced "both" connection may still hold the other role.
        for old in replaced:
            if self.audio is old:
                self.audio = None
            if self.body is old:
                self.body = None
        if self.mouth_task is None or self.mouth_task.done():
            self.mouth_task = asyncio.create_task(self._mouth_sender())
        if self.mode_task is None or self.mode_task.done():
            self.mode_task = asyncio.create_task(self._mode_watcher())
        self.ambient.start()
        self.chatter.start()
        log.info("devices: audio=%s body=%s",
                 self.audio.name if self.audio else "-", self.body.name if self.body else "-")
        return list({id(c): c for c in replaced}.values())

    def attach_aux(self, conn: Conn) -> list[Conn]:
        """Register a presence-only listener; returns an earlier connection from the
        same device that it replaces. Touches no skeleton state."""
        replaced = [c for c in self.aux if c.name == conn.name]
        self.aux = [c for c in self.aux if c not in replaced] + [conn]
        log.info("aux clients: %s", ", ".join(c.name for c in self.aux))
        self._notify_aux([conn])  # tell the newcomer the current state
        return replaced

    def detach_aux(self, conn: Conn) -> None:
        if conn in self.aux:
            self.aux.remove(conn)
            log.info("aux clients: %s", ", ".join(c.name for c in self.aux) or "-")

    def set_presence(self, present: bool, force: bool = False) -> None:
        """Record the presence state and tell aux clients when it changes (or always,
        if `force`: a manual click in the admin UI is resent even if state is unchanged)."""
        if force or present != self.present:
            self.present = present
            self._notify_aux(self.aux)

    def _notify_aux(self, targets: list[Conn]) -> None:
        """Fire-and-forget {"type":"presence"} to aux clients. Runs in its own task
        with a timeout so a slow or dead listener can't delay the skeleton."""
        if not targets:
            return
        msg = json.dumps({"type": "presence", "present": self.present})
        log.info("presence %s -> notifying aux: %s", "arrived" if self.present else "left",
                 ", ".join(c.name for c in targets))

        async def one(conn: Conn) -> None:
            try:
                await asyncio.wait_for(conn.send(msg), 2.0)
            except Exception as e:  # noqa: BLE001
                log.warning("aux %s unreachable (%s); dropping it", conn.name, e or type(e).__name__)
                self.detach_aux(conn)
                asyncio.ensure_future(conn.ws.close())

        for conn in list(targets):
            task = asyncio.create_task(one(conn))
            self._aux_tasks.add(task)
            task.add_done_callback(self._aux_tasks.discard)

    def detach(self, conn: Conn) -> None:
        lost_audio = self.audio is conn
        lost_body = self.body is conn
        if self.audio is conn:
            self.audio = None
        if self.body is conn:
            self.body = None
        if lost_audio and self.conv_task and not self.conv_task.done():
            log.warning("audio device left mid-conversation; ending it")
            self.conv_task.cancel()
        if lost_body:
            self.set_presence(False)  # no radar any more: don't leave aux clients stuck on "present"
        log.info("devices: audio=%s body=%s",
                 self.audio.name if self.audio else "-", self.body.name if self.body else "-")

    # ---------- transport ----------
    async def _send(self, conn: Conn | None, data) -> None:
        if conn is None:
            return
        try:
            await conn.send(data)
        except ConnectionClosed:
            pass

    async def send_audio_json(self, obj: dict) -> None:
        await self._send(self.audio, json.dumps(obj))

    async def send_audio_bytes(self, data: bytes) -> None:
        if self.audio is None:
            raise ConnectionClosed(None, None)
        await self.audio.send(data)

    async def send_body_json(self, obj: dict) -> None:
        await self._send(self.body, json.dumps(obj))

    async def _body_request(self, msg: dict, waiters: list[asyncio.Future], what: str, timeout: float) -> dict:
        if self.body is None:
            raise RuntimeError("no body device connected")
        if self.conv_task and not self.conv_task.done():
            log.warning("%s command (%s) sent mid-conversation", what, msg.get("type"))
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        waiters.append(fut)
        try:
            await self.send_body_json(msg)
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"no reply from the body device (is the {what} firmware updated?)") from None
        finally:
            if fut in waiters:
                waiters.remove(fut)

    async def jaw_request(self, msg: dict, timeout: float = 3.0) -> dict:
        """Send a jaw_config / jaw_test / jaw_get to the body and wait for its jaw_config reply."""
        return await self._body_request(msg, self._jaw_waiters, "jaw", timeout)

    async def led_request(self, msg: dict, timeout: float = 3.0) -> dict:
        """Send a led_config / led_test / led_get to the body and wait for its led_config reply."""
        return await self._body_request(msg, self._led_waiters, "LED", timeout)

    async def send_state(self, state: str) -> None:
        msg = json.dumps({"type": "state", "state": state, "mode": self.mode})
        await self._send(self.audio, msg)
        if self.body is not self.audio:
            await self._send(self.body, msg)

    def schedule_mouth(self, due: float, env: int) -> None:
        # Only needed when the body is a separate device; a "both" device gets the
        # level inside each audio frame already.
        if self.body is not None and self.body is not self.audio:
            self.mouth_q.put_nowait((due + self.cfg.mouth_delay_s, env))

    async def _mode_watcher(self) -> None:
        """Keep the body's eye color in step with the persona mode (clock, mode.txt)."""
        while True:
            if not (self.conv_task and not self.conv_task.done()):
                self.mode = current_mode(self.cfg)  # mid-conversation the mode stays fixed
            if self.body is not None and self._announced != (id(self.body), self.mode):
                self._announced = (id(self.body), self.mode)
                log.info("mode -> %s (told body)", self.mode)
                await self.send_body_json({"type": "mode", "mode": self.mode})
            await asyncio.sleep(1.0)

    async def _mouth_sender(self) -> None:
        while True:
            due, env = await self.mouth_q.get()
            delay = due - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            elif delay < -0.2 and env != 0:
                continue  # hopelessly late; skip (but always deliver "close")
            await self._send(self.body, P.pack_mouth(env))

    def new_play_id(self) -> int:
        self._play_id += 1
        self._waiters[self._play_id] = asyncio.Event()
        return self._play_id

    async def wait_playback_done(self, play_id: int, timeout: float) -> None:
        ev = self._waiters.get(play_id)
        if ev is None:
            return
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            log.debug("playback %d confirmed after %.2fs", play_id, time.monotonic() - t0)
        except asyncio.TimeoutError:
            log.warning("device never confirmed playback %d within %.1fs; continuing", play_id, timeout)
        finally:
            self._waiters.pop(play_id, None)

    # ---------- inbound ----------
    def on_mic(self, pcm: bytes) -> None:
        if self.mic_mode != "forward":
            return
        if self.mic_q.full():
            self.mic_q.get_nowait()
        self.mic_q.put_nowait(pcm)

    def set_mic(self, mode: str) -> None:
        self.mic_mode = mode
        if mode == "drop":
            while not self.mic_q.empty():
                self.mic_q.get_nowait()

    def _save_photo(self, jpeg: bytes) -> str | None:
        """Write a frame to PHOTOS_DIR for debugging; keep only the newest PHOTOS_KEEP.
        PHOTOS_KEEP=0 (the default) saves nothing: frames are of visitors, often kids."""
        if self.cfg.photos_keep <= 0:
            return None
        try:
            d = self.cfg.photos_dir
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.jpg"
            path.write_bytes(jpeg)
            for old in sorted(d.glob("*.jpg"))[: -self.cfg.photos_keep]:
                old.unlink(missing_ok=True)
            return path.name
        except OSError as e:
            log.warning("could not save photo: %s", e)
            return None

    async def on_json(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "hello":
            pass  # handled by the server at connect time
        elif (t == "trigger" or (t == "presence" and msg.get("present"))) and not self.sensor_enabled:
            log.info("motion sensor disabled in the admin UI: ignoring %s", t)
        elif t == "trigger" or (t == "presence" and msg.get("present")):
            self.set_presence(True)
            self.start_conversation()
        elif t == "presence" and not msg.get("present"):
            self.set_presence(False)
            self.mark_left()
        elif t == "image":
            try:
                jpeg = base64.b64decode(msg["jpeg_b64"])
                if self.cfg.camera_rotate_180:
                    try:
                        jpeg = await asyncio.to_thread(rotate_jpeg_180, jpeg)
                    except Exception as e:  # noqa: BLE001
                        log.warning("could not rotate camera frame, using it as sent: %s", e)
                self.image_q.put_nowait(jpeg)
                self.recent_photos.append((time.time(), jpeg))
                saved = self._save_photo(jpeg)
                log.info("camera frame received: %d bytes -> %s", len(jpeg), saved or "not saved")
            except Exception as e:  # noqa: BLE001
                log.warning("bad image message: %s", e)
        elif t == "led_config":
            self.leds = {"eyes": msg.get("eyes"), "mouth": msg.get("mouth"),
                         "saved": bool(msg.get("saved"))}
            log.info("leds: eyes %.2f mouth %.2f (%s)", float(msg.get("eyes") or 0), float(msg.get("mouth") or 0),
                     "saved" if msg.get("saved") else "not saved")
            for fut in self._led_waiters:
                if not fut.done():
                    fut.set_result(self.leds)
        elif t == "jaw_config":
            self.jaw = {"closed": msg.get("closed"), "open": msg.get("open"),
                        "saved": bool(msg.get("saved"))}
            log.info("jaw: closed %s open %s (%s)", msg.get("closed"), msg.get("open"),
                     "saved" if msg.get("saved") else "not saved")
            for fut in self._jaw_waiters:
                if not fut.done():
                    fut.set_result(self.jaw)
        elif t == "playback_done":
            ev = self._waiters.get(int(msg.get("id", -1)))
            if ev:
                ev.set()
        else:
            log.debug("unknown message: %s", t)

    def start_conversation(self) -> None:
        if self.audio is None:
            log.info("trigger ignored: no audio device connected")
            return
        if self.announcing:
            log.info("trigger ignored: playing an announcement")
            return
        if self.conv_task and not self.conv_task.done():
            log.info("trigger ignored: conversation already running")
            return
        if time.monotonic() < self.cooldown_until:
            log.info("trigger ignored: cooldown (%.0fs left)", self.cooldown_until - time.monotonic())
            return
        self.chatter.interrupt()  # a random phrase in progress gives way to the visitor
        self.conv_task = asyncio.create_task(self.conversation())

    def mark_left(self) -> None:
        if self.conv_task and not self.conv_task.done():
            log.info("visitor left")
            self.leave_requested = True
        else:
            log.info("'visitor left' ignored: no conversation active")

    def start_announcement(self, text: str) -> None:
        """Admin UI 'play this out loud': synthesize `text` verbatim in the
        current persona's voice and play it to the audio device, the same
        way a greeting plays. Not sent to the model — no AI turn happens.
        Fires in the background, like start_conversation(), since playback
        is paced in real time and would otherwise hang the HTTP request."""
        if self.audio is None:
            raise RuntimeError("no audio device connected")
        if self.conv_task and not self.conv_task.done():
            raise RuntimeError("a conversation is in progress")
        if self.announcing:
            raise RuntimeError("already playing an announcement")
        if self.chatter.speaking:
            raise RuntimeError("a random phrase is playing; try again in a moment")
        self.announcing = True
        asyncio.create_task(self._speak_text(text))

    async def _speak_text(self, text: str) -> None:
        try:
            await self.ambient.fade_out()
            cfg = effective_settings(self.env_cfg)
            mode = current_mode(cfg)
            mcfg = cfg_for_mode(cfg, mode)
            log.info("admin announcement (%s, voice %s): %s", mode, mcfg.voice, text)
            if cfg.use_gemini:
                pcm, rate, _ = await synthesize_line(mcfg, mode, text)
            else:
                pcm, rate = echo_tone(), 16_000
            self.active_cfg = mcfg
            await self.send_state("speaking")
            await self.play_pcm16(pcm, rate)
        except Exception:  # noqa: BLE001
            log.exception("announcement failed")
        finally:
            self.announcing = False
            self.ambient.hold()
            await self.send_state("idle")

    # ---------- conversation ----------
    async def play_pcm16(self, pcm: bytes, rate: int) -> None:
        fx = VoiceFX(self.active_cfg, rate)
        player = Player(self)
        await player.begin()
        x = pcm16_to_float(pcm)
        step = rate // 10
        for i in range(0, x.size, step):
            await player.feed(fx.process(x[i : i + step]))
        await player.feed(fx.flush())
        await player.end()

    async def _forward_mic(self, brain) -> None:
        while True:
            chunks = [await self.mic_q.get()]
            while not self.mic_q.empty() and len(chunks) < 5:  # batch up to ~100 ms
                chunks.append(self.mic_q.get_nowait())
            if self.mic_mode == "forward":
                await brain.send_audio(b"".join(chunks))

    async def _capture_and_describe(self, cfg: Config):
        # Give the visitor a moment to step in front of the camera before shooting.
        await asyncio.sleep(cfg.vision_delay_s)
        await self.send_body_json(
            {"type": "capture", "count": cfg.vision_frames, "interval_ms": cfg.vision_interval_ms}
        )
        return await self.vision.describe_from_queue(self.image_q, cfg.vision_frames)

    async def conversation(self) -> None:
        self.cfg = cfg = effective_settings(self.env_cfg)  # pick up admin UI overrides
        started = time.monotonic()
        self.leave_requested = False
        while not self.image_q.empty():
            self.image_q.get_nowait()
        self.mode = current_mode(cfg)
        self.active_cfg = mcfg = cfg_for_mode(cfg, self.mode)
        log.info("=== visitor detected (%s mode, voice %s) ===", self.mode, mcfg.voice)
        await self.send_state("greeting")
        fade = asyncio.create_task(self.ambient.fade_out())  # music out while the brain connects

        self.brain = brain = make_brain(mcfg)
        brain_task = asyncio.create_task(brain.start(persona_prompt(mcfg, self.mode)))
        vision_task = None
        if cfg.vision_enabled and self.body is not None:
            vision_task = asyncio.create_task(self._capture_and_describe(cfg))
        forwarder: asyncio.Task | None = None
        try:
            await fade  # the speaker must be quiet before the greeting starts
            greeting = random.choice(self.greetings[self.mode])
            log.info("greeting: %s", greeting.text)
            await self.play_pcm16(greeting.pcm, greeting.rate)

            # From here on, the visitor may answer. Buffer mic audio until the brain is ready.
            self.set_mic("forward")
            await asyncio.wait_for(brain_task, cfg.connect_timeout_s)

            scene = None
            if vision_task is not None:
                try:
                    scene = await asyncio.wait_for(vision_task, cfg.vision_grace_s)
                except asyncio.TimeoutError:
                    log.info("vision too slow; continuing without costume info")
                except Exception as e:  # noqa: BLE001
                    log.warning("vision failed: %s", e)
            note = scene_note(scene)
            log.info("%s", note)
            await brain.add_context(note, greeting.text)

            forwarder = asyncio.create_task(self._forward_mic(brain))
            await self.send_state("listening")
            await self._dialogue(brain, started)
        except asyncio.TimeoutError:
            log.error("brain did not connect within %.0fs", cfg.connect_timeout_s)
        except ConnectionClosed:
            pass
        except Exception:  # noqa: BLE001
            log.exception("conversation failed")
        finally:
            self.set_mic("drop")
            for task in (forwarder, vision_task, brain_task):
                if task and not task.done():
                    task.cancel()
            await brain.close()
            self.brain = None
            self.cooldown_until = time.monotonic() + cfg.cooldown_s
            log.info("=== conversation over (%.0fs) ===", time.monotonic() - started)
            await self.send_state("idle")

    async def _dialogue(self, brain, started: float) -> None:
        cfg = self.cfg
        turns = 0
        nudged = False
        ending = False
        listen_since = time.monotonic()
        last_heard: float | None = None
        while True:
            if self.leave_requested and self.mic_mode == "forward" and not ending:
                return  # they walked away while we were listening
            waited = time.monotonic() - listen_since
            if waited >= cfg.silence_timeout_s:
                if ending or nudged or self.leave_requested:
                    return
                nudged = True
                log.info("silence -> nudge")
                self.set_mic("drop")
                await brain.end_input()
                await brain.say(MODES[self.mode].nudge)
                listen_since = time.monotonic()
                continue
            try:
                ev = await asyncio.wait_for(brain.events.get(), min(0.5, cfg.silence_timeout_s - waited))
            except asyncio.TimeoutError:
                continue

            kind = ev[0]
            if kind == "user_text":
                log.info("visitor: %s", ev[1])
                listen_since = last_heard = time.monotonic()
            elif kind in ("error", "closed"):
                log.warning("brain session ended: %s", ev[1] if len(ev) > 1 else kind)
                return
            elif kind == "audio":
                if last_heard is not None:
                    log.info("reply latency: %.2fs after last transcript", time.monotonic() - last_heard)
                    last_heard = None
                self.set_mic("drop")
                await brain.end_input()
                await self._speak(brain, ev[1])
                turns += 1
                if ending:
                    return
                if (
                    self.leave_requested
                    or turns >= cfg.max_turns
                    or time.monotonic() - started >= cfg.max_conversation_s
                ):
                    ending = True
                    await brain.say(MODES[self.mode].goodbye)
                else:
                    self.set_mic("forward")
                    await self.send_state("listening")
                listen_since = time.monotonic()
            # model_text / turn_complete outside a reply: ignore

    async def _speak(self, brain, first_chunk: bytes) -> None:
        await self.send_state("speaking")
        fx = VoiceFX(self.active_cfg, brain.out_rate)
        player = Player(self)
        await player.begin()
        await player.feed(fx.process_pcm16(first_chunk))
        said: list[str] = []
        while True:
            try:
                ev = await asyncio.wait_for(brain.events.get(), self.cfg.turn_stall_s)
            except asyncio.TimeoutError:
                log.warning("reply stalled; cutting it off")
                break
            kind = ev[0]
            if kind == "audio":
                await player.feed(fx.process_pcm16(ev[1]))
            elif kind == "model_text":
                said.append(ev[1])
            elif kind == "user_text":
                log.info("visitor: %s", ev[1])
            elif kind in ("turn_complete", "error", "closed"):
                if kind != "turn_complete":
                    brain.events.put_nowait(ev)  # let _dialogue see it
                break
        await player.feed(fx.flush())
        await player.end()
        log.info("skeleton: %s", "".join(said).strip())


class Server:
    HELLO_TIMEOUT_S = 5

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.vision = Vision(cfg)
        self.hub: Hub | None = None
        log_ring.install()

    async def handler(self, ws: ServerConnection) -> None:
        # First message must be hello {role}. Missing role = "both" (Mac simulator).
        try:
            first = await asyncio.wait_for(ws.recv(), self.HELLO_TIMEOUT_S)
            hello = json.loads(first) if isinstance(first, str) else {}
        except (asyncio.TimeoutError, json.JSONDecodeError, ConnectionClosed):
            hello = {}
        if hello.get("type") != "hello":
            log.warning("device %s didn't say hello; disconnecting", client_ip(ws))
            await ws.close()
            return
        role = hello.get("role", "both")
        if role not in ("audio", "body", "both", "aux"):
            log.warning("unknown role %r; disconnecting", role)
            await ws.close()
            return
        conn = Conn(ws, role, f"{hello.get('device', '?')}@{client_ip(ws)}")
        log.info("device connected: %s as %s", conn.name, role)
        hub = self.hub
        if role == "aux":
            # Presence listener: we only talk to it. Anything it sends is ignored, so it
            # can never trigger a conversation or reach the audio/body devices.
            for old in hub.attach_aux(conn):
                log.info("replacing %s", old.name)
                await old.ws.close()
            try:
                async for _ in ws:
                    pass
            except ConnectionClosed:
                pass
            finally:
                log.info("aux disconnected: %s", conn.name)
                hub.detach_aux(conn)
            return
        for old in hub.attach(conn):
            log.info("replacing %s", old.name)
            await old.ws.close()
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    if conn.does_audio:
                        hub.on_mic(msg)
                else:
                    try:
                        await hub.on_json(json.loads(msg))
                    except json.JSONDecodeError:
                        log.warning("bad JSON from %s", conn.name)
        except ConnectionClosed:
            pass
        finally:
            log.info("device disconnected: %s", conn.name)
            hub.detach(conn)

    async def run(self) -> None:
        mode = "Gemini Live" if self.cfg.use_gemini else "ECHO (no API key / BRAIN=echo)"
        log.info("brain: %s", mode)
        greetings = await ensure_greetings(self.cfg)
        for mode, items in greetings.items():
            log.info("%s mode: %d greeting(s)", mode, len(items))
        c = self.cfg
        clock = f"pretending it's {c.pretend_time}" if c.pretend_time else "real clock"
        log.info("persona: %s -> %s now (scary %s-%s, %s)", requested_mode(c), current_mode(c),
                 c.scary_start, c.scary_end, clock)
        if c.mode_file.exists():
            log.warning("%s exists and says %r: it overrides --mode / PERSONA_MODE "
                        "(rm %s to clear)", c.mode_file.name, c.mode_file.read_text().strip(),
                        c.mode_file.name)
        self.hub = Hub(self.cfg, greetings, self.vision)
        self._chatter_prep = asyncio.create_task(self.hub.chatter.prepare())  # don't block startup

        async def serve_ws() -> None:
            if not self.cfg.device_token:
                log.warning("DEVICE_TOKEN is not set: the device WebSocket accepts anyone. "
                            "Set it before exposing port %d to the internet.", self.cfg.port)
            async with serve(self.handler, self.cfg.host, self.cfg.port, max_size=8 * 1024 * 1024,
                             process_request=make_auth_check(self.cfg.device_token)) as srv:
                log.info("listening on ws://%s:%d (device token %s)", self.cfg.host, self.cfg.port,
                         "required" if self.cfg.device_token else "NOT required")
                await srv.serve_forever()

        await asyncio.gather(serve_ws(), run_admin(self.cfg, lambda: self.hub))


def main() -> None:
    ap = argparse.ArgumentParser(description="Talking skeleton server")
    ap.add_argument("--mode", choices=["auto", "family", "scary"],
                    help="persona mode (overrides PERSONA_MODE in .env; mode.txt still wins)")
    ap.add_argument("--pretend-time", metavar="HH:MM",
                    help="pretend it's this time of day, to test auto mode switching")
    args = ap.parse_args()
    cfg = load_config()
    if args.mode:
        cfg = replace(cfg, persona_mode=args.mode)
    if args.pretend_time:
        try:
            _hhmm(args.pretend_time)
        except ValueError:
            ap.error("--pretend-time must look like 21:15")
        cfg = replace(cfg, pretend_time=args.pretend_time)
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    try:
        asyncio.run(Server(cfg).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
