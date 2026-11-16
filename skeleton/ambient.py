"""Background audio: loops an mp3 on the speaker while nobody is talking to the
skeleton, and fades it out before any speech (greeting, reply, admin "say").

The audio device has one playback buffer and no mixer, so this must never
overlap with speech. A supervisor task decides when the music is wanted (switched
on in the admin UI, device connected, no conversation / announcement / cooldown)
and starts or fades out the streaming loop to match. Speech paths call
`fade_out()` first so the hand-off is clean.

Volume is applied here, on the PCM, so the skeleton voice keeps full level (the
firmware's `volume` message is global and would turn that down too).
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soxr
from websockets.exceptions import ConnectionClosed

from . import protocol as P
from .fx import float_to_pcm16
from .settings_store import effective as effective_settings

if TYPE_CHECKING:
    from .server import Hub

log = logging.getLogger("skeleton.ambient")

FADE_S = 1.5         # fade-out length
FADE_IN_S = 1.0      # fade-in length when the music starts or resumes
LEAD_S = 0.1         # how far ahead of real time the device may buffer (less than speech, so fades react fast)
RESUME_DELAY_S = 2.0  # quiet gap after speech before the music comes back
FRAMES_PER_S = 1000 // P.FRAME_MS


def list_files(directory: Path) -> list[str]:
    try:
        return sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".mp3")
    except OSError:
        return []


def decode_mono_16k(path: Path) -> np.ndarray:
    """Decode an audio file to mono float32 at the device rate."""
    from pedalboard.io import AudioFile  # heavy native import; only needed when music is played

    with AudioFile(str(path)) as f:
        audio = f.read(f.frames)  # (channels, frames) float32
        rate = int(f.samplerate)
    mono = audio.mean(axis=0) if audio.shape[0] > 1 else audio[0]
    if rate != P.DEVICE_RATE:
        mono = soxr.resample(mono, rate, P.DEVICE_RATE)
    return np.ascontiguousarray(mono, dtype=np.float32)


def level_to_gain(volume: float) -> float:
    """Slider 0..1 -> amplitude. Squared so the low end of the slider is usable."""
    v = min(1.0, max(0.0, volume))
    return v * v


class Ambient:
    def __init__(self, hub: "Hub"):
        self.hub = hub
        cfg = effective_settings(hub.env_cfg)
        self.file = cfg.ambient_file
        self.volume = cfg.ambient_volume
        self.enabled = False  # always off after a restart; switched on from the admin UI
        self.error: str | None = None
        self.hold_until = 0.0
        self._task: asyncio.Task | None = None
        self._super: asyncio.Task | None = None
        self._fading = False
        self._cache: tuple[str, float, np.ndarray] | None = None  # (name, mtime, samples)

    # ---------- public ----------
    @property
    def directory(self) -> Path:
        return self.hub.env_cfg.ambient_dir

    def files(self) -> list[str]:
        return list_files(self.directory)

    @property
    def playing(self) -> bool:
        return self._running and not self._fading

    @property
    def _running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._super is None or self._super.done():
            self._super = asyncio.create_task(self._supervise())

    def configure(self, *, enabled: bool | None = None, file: str | None = None,
                  volume: float | None = None) -> None:
        if file is not None:
            if file not in self.files():
                raise ValueError(f"unknown file {file!r}")
            self.file = file
        if volume is not None:
            self.volume = min(1.0, max(0.0, float(volume)))
        if enabled is not None:
            self.enabled = enabled
            if enabled:
                self.error = None

    def hold(self, seconds: float = RESUME_DELAY_S) -> None:
        """Keep the music off for a moment (e.g. after speech ends)."""
        self.hold_until = max(self.hold_until, time.monotonic() + seconds)

    async def fade_out(self) -> None:
        """Fade the music to silence and flush the device buffer. Returns when it's quiet."""
        if not self._running:
            return
        self._fading = True
        task = self._task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass  # _run logs its own errors

    # ---------- internals ----------
    def _wanted(self) -> bool:
        hub = self.hub
        return (
            self.enabled
            and hub.audio is not None
            and not hub.announcing
            and not hub.chatter.speaking
            and not (hub.conv_task and not hub.conv_task.done())
            and time.monotonic() >= max(hub.cooldown_until, self.hold_until)
        )

    async def _supervise(self) -> None:
        while True:
            try:
                wanted = self._wanted()
                if wanted and not self._running:
                    self._fading = False
                    self._task = asyncio.create_task(self._run())
                elif not wanted and self._running:
                    self._fading = True
            except Exception:  # noqa: BLE001
                log.exception("ambient supervisor error")
            await asyncio.sleep(0.25)

    async def _samples(self) -> np.ndarray:
        path = self.directory / self.file
        mtime = path.stat().st_mtime
        if self._cache and self._cache[:2] == (self.file, mtime):
            return self._cache[2]
        t0 = time.monotonic()
        samples = await asyncio.to_thread(decode_mono_16k, path)
        log.info("ambient: decoded %s (%.0fs) in %.1fs", self.file, samples.size / P.DEVICE_RATE,
                 time.monotonic() - t0)
        self._cache = (self.file, mtime, samples)
        return samples

    async def _run(self) -> None:
        hub = self.hub
        try:
            try:
                samples = await self._samples()
            except Exception as e:  # noqa: BLE001
                log.exception("ambient: cannot load %s", self.file)
                self.error = f"cannot load {self.file}: {e}"
                self.enabled = False
                return
            if samples.size < P.FRAME_SAMPLES:
                self.error = f"{self.file} is empty"
                self.enabled = False
                return
            name = self.file
            log.info("ambient: playing %s", name)
            pos = 0
            gain = 0.0
            fade_step = 0.0  # per-frame decrease while fading, fixed when the fade starts
            sent = 0
            t0 = time.monotonic()
            while True:
                if self.file != name:  # file changed in the UI: switch tracks
                    try:
                        samples = await self._samples()
                    except Exception as e:  # noqa: BLE001
                        log.exception("ambient: cannot load %s", self.file)
                        self.error = f"cannot load {self.file}: {e}"
                        self.enabled = False
                        return
                    name, pos = self.file, 0
                n = P.FRAME_SAMPLES
                end = pos + n
                if end <= samples.size:
                    frame = samples[pos:end]
                else:  # wrap seamlessly
                    frame = np.concatenate([samples[pos:], samples[: end - samples.size]])
                pos = end % samples.size

                target = level_to_gain(self.volume)
                if self._fading:
                    if fade_step == 0.0:
                        fade_step = max(gain, 1e-6) / (FADE_S * FRAMES_PER_S)
                    new_gain = max(0.0, gain - fade_step)
                else:
                    step = 1.0 / (FADE_IN_S * FRAMES_PER_S)  # also smooths slider moves
                    new_gain = min(target, gain + step) if gain < target else max(target, gain - step)
                ramp = np.linspace(gain, new_gain, n, endpoint=False, dtype=np.float32)
                gain = new_gain
                pcm = float_to_pcm16(frame * ramp)

                now = time.monotonic()
                ahead = sent / P.DEVICE_RATE - (now - t0)
                if ahead < 0:
                    t0 = now - sent / P.DEVICE_RATE
                elif ahead > LEAD_S:
                    await asyncio.sleep(ahead - LEAD_S)
                await hub.send_audio_bytes(P.pack_audio(0, pcm))  # env 0: the jaw stays shut for music
                sent += n

                if self._fading and gain == 0.0:
                    await asyncio.sleep(LEAD_S)  # let the silent tail reach the speaker
                    await hub.send_audio_json({"type": "stop"})
                    log.info("ambient: faded out")
                    return
        except ConnectionClosed:
            log.info("ambient: audio device went away")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("ambient: playback failed")
            self.error = "playback failed (see log)"
            self.enabled = False
        finally:
            self._fading = False
