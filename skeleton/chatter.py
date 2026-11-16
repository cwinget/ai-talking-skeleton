"""Random-phrases mode: while switched on in the admin UI, the skeleton says a
funny (family) or spooky (scary) phrase every CHATTER_INTERVAL_S seconds, whether
or not anyone is there. It never talks over a conversation or an announcement, and a
visitor arriving mid-phrase cuts it off so the greeting isn't lost.

Phrases live next to the greetings: greetings/<mode>/phrases/lines.txt (one per
line, seeded from prompts.PHRASES) plus one WAV per line, named after a hash of
voice+text so changing the voice regenerates them. Missing WAVs are generated in
the background at launch (needs a Gemini key; without one a tone plays instead).
Like the background music, the on/off switch is in memory only.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .brain import echo_tone
from .config import Config
from .greetings import read_wav, synthesize_line, write_wav
from .modes import cfg_for_mode, current_mode
from .prompts import MODES, PHRASES
from .settings_store import effective as effective_settings

if TYPE_CHECKING:
    from .server import Hub

log = logging.getLogger("skeleton.chatter")

MAX_PHRASES = 100
MAX_LEN = 200
FIRST_DELAY_S = 1.0  # first phrase this long after switching on


@dataclass
class Phrase:
    text: str
    pcm: bytes | None = None  # None = no audio yet (or no API key)
    rate: int = 24_000


def phrases_dir(mcfg: Config) -> Path:
    return mcfg.greetings_dir / "phrases"


def lines_path(mcfg: Config, mode: str) -> Path:
    p = phrases_dir(mcfg) / "lines.txt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {mode} random phrases: one per line. Lines starting with # are ignored.\n"
                     + "\n".join(PHRASES[mode]) + "\n")
    return p


def read_lines(mcfg: Config, mode: str) -> list[str]:
    return [ln.strip() for ln in lines_path(mcfg, mode).read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def wav_path(mcfg: Config, text: str) -> Path:
    key = hashlib.sha1(f"{mcfg.voice}|{text}".encode()).hexdigest()[:12]
    return phrases_dir(mcfg) / f"phrase_{key}.wav"


def clean_phrase(text: object) -> str:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    t = " ".join(text.split())
    if not t:
        raise ValueError("phrase is empty")
    if len(t) > MAX_LEN:
        raise ValueError(f"phrase is too long (max {MAX_LEN} characters)")
    if t.startswith("#"):
        raise ValueError("phrase can't start with #")
    return t


class Chatter:
    def __init__(self, hub: "Hub"):
        self.hub = hub
        self.enabled = False  # always off after a restart
        self.speaking = False
        self.error: str | None = None
        self.pool: dict[str, list[Phrase]] = {m: [] for m in MODES}
        self._due = 0.0
        self._last: str | None = None
        self._super: asyncio.Task | None = None
        self._speak_task: asyncio.Task | None = None
        self._gen_lock = asyncio.Lock()
        self._bg: set[asyncio.Task] = set()

    @property
    def interval_s(self) -> float:
        return self.hub.env_cfg.chatter_interval_s

    # ---------- phrase storage ----------
    def _mcfg(self, mode: str) -> Config:
        return cfg_for_mode(effective_settings(self.hub.env_cfg), mode)

    def load(self) -> None:
        """Read lines.txt and any matching WAVs for each mode into memory."""
        for mode in MODES:
            mcfg = self._mcfg(mode)
            items = []
            for text in read_lines(mcfg, mode):
                path = wav_path(mcfg, text)
                pcm, rate = (None, 24_000)
                if path.exists():
                    try:
                        pcm, rate = read_wav(path)
                    except Exception:  # noqa: BLE001
                        log.warning("unreadable %s; will regenerate", path.name)
                items.append(Phrase(text, pcm or None, rate))
            self.pool[mode] = items

    async def prepare(self) -> None:
        """Launch-time: load phrases and generate any missing audio. Runs in the
        background so the server doesn't wait on it."""
        try:
            self.load()
            await self._generate_missing()
        except Exception:  # noqa: BLE001
            log.exception("could not prepare random phrases")

    async def _generate_missing(self) -> None:
        cfg = effective_settings(self.hub.env_cfg)
        if not cfg.use_gemini:
            return
        async with self._gen_lock:
            for mode in MODES:
                mcfg = self._mcfg(mode)
                todo = [p for p in self.pool[mode] if p.pcm is None]
                if todo:
                    log.info("[%s] generating %d phrase(s) with voice %s", mode, len(todo), mcfg.voice)
                for ph in todo:
                    try:
                        pcm, rate, _ = await synthesize_line(mcfg, mode, ph.text)
                        if not pcm:
                            raise RuntimeError("no audio returned")
                        phrases_dir(mcfg).mkdir(parents=True, exist_ok=True)
                        write_wav(wav_path(mcfg, ph.text), pcm, rate)
                        ph.pcm, ph.rate = pcm, rate
                    except Exception as e:  # noqa: BLE001
                        log.warning("[%s] could not generate phrase %r: %s", mode, ph.text[:40], e)
                self._prune(mcfg, mode)

    def _prune(self, mcfg: Config, mode: str) -> None:
        """Delete WAVs no line refers to any more (old voice, removed line)."""
        keep = {wav_path(mcfg, p.text).name for p in self.pool[mode]}
        for f in phrases_dir(mcfg).glob("phrase_*.wav"):
            if f.name not in keep:
                f.unlink(missing_ok=True)

    def add(self, text: object) -> str:
        """Add a phrase to every mode's rotation (each is voiced by that mode's voice)."""
        t = clean_phrase(text)
        if any(p.text.lower() == t.lower() for p in self.pool[next(iter(MODES))]):
            raise ValueError("that phrase is already in the rotation")
        if len(self.pool[next(iter(MODES))]) >= MAX_PHRASES:
            raise ValueError(f"too many phrases (max {MAX_PHRASES})")
        for mode in MODES:
            path = lines_path(self._mcfg(mode), mode)
            body = path.read_text()
            path.write_text(body + ("" if body.endswith("\n") else "\n") + t + "\n")
            self.pool[mode].append(Phrase(t))
        log.info("added phrase: %s", t)
        task = asyncio.create_task(self._generate_missing())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return t

    def listing(self, mode: str) -> list[dict]:
        have_audio = self.hub.env_cfg.use_gemini
        return [{"text": p.text, "ready": p.pcm is not None or not have_audio} for p in self.pool[mode]]

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._super is None or self._super.done():
            self._super = asyncio.create_task(self._supervise())

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self.enabled:
            self._due = time.monotonic() + FIRST_DELAY_S
            self.error = None
        self.enabled = enabled
        if not enabled:
            self.interrupt()  # stop mid-phrase too

    def interrupt(self) -> None:
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()

    def _can_speak(self) -> bool:
        hub = self.hub
        return (
            hub.audio is not None
            and not hub.announcing
            and not (hub.conv_task and not hub.conv_task.done())
            and time.monotonic() >= hub.cooldown_until
        )

    async def _supervise(self) -> None:
        while True:
            try:
                if (self.enabled and not self.speaking and time.monotonic() >= self._due
                        and self._can_speak()):
                    self._speak_task = asyncio.create_task(self._speak())
                    await asyncio.wait({self._speak_task})
                    self._due = time.monotonic() + self.interval_s
            except Exception:  # noqa: BLE001
                log.exception("chatter supervisor error")
                self._due = time.monotonic() + self.interval_s
            await asyncio.sleep(0.25)

    def _pick(self, mode: str) -> Phrase | None:
        usable = [p for p in self.pool[mode] if p.pcm is not None or not self.hub.env_cfg.use_gemini]
        if not usable:
            return None
        choices = [p for p in usable if p.text != self._last] or usable
        return random.choice(choices)

    async def _speak(self) -> None:
        hub = self.hub
        interrupted = False
        self.speaking = True
        try:
            cfg = effective_settings(hub.env_cfg)
            mode = current_mode(cfg)
            ph = self._pick(mode)
            if ph is None:
                self.error = "no phrases ready yet" if self.pool[mode] else "no phrases"
                return
            self.error = None
            self._last = ph.text
            await hub.ambient.fade_out()
            if not self._can_speak():  # something started while the music faded
                return
            hub.active_cfg = cfg_for_mode(cfg, mode)
            log.info("random phrase (%s): %s", mode, ph.text)
            await hub.send_state("speaking")
            if ph.pcm is not None:
                await hub.play_pcm16(ph.pcm, ph.rate)
            else:
                await hub.play_pcm16(echo_tone(), 16_000)
        except asyncio.CancelledError:
            interrupted = True
            hub.schedule_mouth(time.monotonic(), 0)  # close the jaw
            try:
                await hub.send_audio_json({"type": "stop"})  # flush what's buffered on the speaker
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception:  # noqa: BLE001
            log.exception("random phrase failed")
        finally:
            self.speaking = False
            hub.ambient.hold()
            if not interrupted:
                await hub.send_state("idle")
