"""Voice effects (pedalboard), resampling to the device rate (soxr), and framing
into 20 ms chunks with a mouth/LED envelope value per chunk."""
from __future__ import annotations

from typing import Iterator

import numpy as np
import soxr
from pedalboard import Distortion, Gain, Limiter, Pedalboard, Reverb

from . import protocol as P
from .config import Config


class LowLatencyPitch:
    """Streaming delay-line pitch shifter (two crossfaded taps).

    pedalboard's PitchShift sounds cleaner but buffers ~1.1 s when streaming,
    which would add a second of dead air before every reply. This one adds
    ~window/2 (~25 ms) of latency. It has a slight warble, which suits a skeleton.
    """

    def __init__(self, semitones: float, rate: int, window_ms: float = 50.0):
        self.ratio = 2.0 ** (semitones / 12.0)
        self.W = max(64, int(rate * window_ms / 1000))
        self.inc = (1.0 - self.ratio) / self.W  # phase advance per sample
        self.hist = np.zeros(self.W + 2, dtype=np.float32)
        self.phase = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.size
        if n == 0:
            return x
        H = self.hist.size
        # Trailing guard sample: at phase 0 the interpolation reads index i0 + 1,
        # one past the newest input sample (its weight is 0, but it must exist).
        buf = np.concatenate([self.hist, x.astype(np.float32), np.zeros(1, np.float32)])
        k = np.arange(n, dtype=np.float64)
        p1 = (self.phase + k * self.inc) % 1.0
        p2 = (p1 + 0.5) % 1.0
        out = np.zeros(n, dtype=np.float32)
        for p in (p1, p2):
            pos = H + k - p * self.W
            i0 = np.floor(pos).astype(np.int64)
            frac = (pos - i0).astype(np.float32)
            tap = buf[i0] * (1 - frac) + buf[i0 + 1] * frac
            out += tap * (np.sin(np.pi * p) ** 2).astype(np.float32)
        self.phase = float((self.phase + n * self.inc) % 1.0)
        self.hist = buf[-H - 1 : -1].copy()
        return out


def build_board(cfg: Config) -> Pedalboard | None:
    """Everything except pitch (pitch is handled by LowLatencyPitch)."""
    if not cfg.fx_enabled:
        return None
    plugins = []
    if cfg.fx_drive_db > 0:
        plugins.append(Distortion(drive_db=cfg.fx_drive_db))
    if cfg.fx_reverb > 0:
        wet = min(1.0, cfg.fx_reverb)
        plugins.append(
            Reverb(room_size=0.6, damping=0.5, wet_level=wet, dry_level=1.0 - wet * 0.5, width=0.0)
        )
    plugins.append(Gain(gain_db=cfg.fx_gain_db))
    plugins.append(Limiter(threshold_db=-1.0))
    return Pedalboard(plugins)


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


class VoiceFX:
    """Streaming FX + resample for one utterance. Create a new one per utterance."""

    def __init__(self, cfg: Config, in_rate: int):
        self.cfg = cfg
        self.in_rate = in_rate
        self._carry = b""
        self.board = build_board(cfg)
        self.pitch = (
            LowLatencyPitch(cfg.fx_pitch, in_rate)
            if cfg.fx_enabled and abs(cfg.fx_pitch) > 0.01
            else None
        )
        self.rs = (
            soxr.ResampleStream(in_rate, P.DEVICE_RATE, 1, dtype="float32")
            if in_rate != P.DEVICE_RATE
            else None
        )

    def process_pcm16(self, pcm: bytes) -> np.ndarray:
        pcm = self._carry + pcm
        if len(pcm) % 2:  # never split a 16-bit sample across chunks
            pcm, self._carry = pcm[:-1], pcm[-1:]
        else:
            self._carry = b""
        return self.process(pcm16_to_float(pcm))

    def process(self, x: np.ndarray, last: bool = False) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if self.pitch is not None and x.size:
            x = self.pitch.process(x)
        if self.board is not None and x.size:
            x = self.board(x[np.newaxis, :], self.in_rate, reset=False)[0]
        if self.rs is not None:
            x = self.rs.resample_chunk(np.ascontiguousarray(x, dtype=np.float32), last=last)
        return np.asarray(x, dtype=np.float32)

    def flush(self) -> np.ndarray:
        """Push silence through so reverb/pitch-shift tails come out."""
        tail = np.zeros(int(self.cfg.fx_tail_s * self.in_rate), dtype=np.float32)
        return self.process(tail, last=True)


class Framer:
    """Accumulates 16 kHz float audio and emits (env, pcm_bytes) 20 ms frames."""

    NOISE_FLOOR = 0.008
    ENV_REF = 0.25  # RMS that maps to a fully-open mouth

    def __init__(self) -> None:
        self.buf = np.zeros(0, dtype=np.float32)

    def push(self, x: np.ndarray) -> Iterator[tuple[int, bytes]]:
        if x.size:
            self.buf = np.concatenate([self.buf, x.astype(np.float32)])
        n = P.FRAME_SAMPLES
        while self.buf.size >= n:
            frame, self.buf = self.buf[:n], self.buf[n:]
            yield self._pack(frame)

    def flush(self) -> Iterator[tuple[int, bytes]]:
        if self.buf.size:
            frame = np.zeros(P.FRAME_SAMPLES, dtype=np.float32)
            frame[: self.buf.size] = self.buf
            self.buf = np.zeros(0, dtype=np.float32)
            yield self._pack(frame)

    def _pack(self, frame: np.ndarray) -> tuple[int, bytes]:
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < self.NOISE_FLOOR:
            env = 0
        else:
            env = int(min(1.0, (rms / self.ENV_REF) ** 0.6) * 255)
        return env, float_to_pcm16(frame)
