"""Hear the voice FX without running a conversation.

    python -m skeleton.fx_preview greetings/family/greet_01.wav
    python -m skeleton.fx_preview greetings/family/greet_01.wav --pitch -6 --reverb 0.45 --drive 8
    python -m skeleton.fx_preview greetings/family/greet_01.wav --compare   # dry, then wet

Put the values you like into .env (FX_PITCH_SEMITONES, FX_REVERB, FX_DRIVE_DB, FX_GAIN_DB).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import protocol as P
from .config import load_config
from .fx import VoiceFX, pcm16_to_float
from .greetings import read_wav, write_wav


def render(cfg, pcm: bytes, rate: int) -> np.ndarray:
    fx = VoiceFX(cfg, rate)
    x = pcm16_to_float(pcm)
    step = rate // 20  # stream in 50 ms chunks, like the server does
    out = [fx.process(x[i : i + step]) for i in range(0, x.size, step)]
    out.append(fx.flush())
    return np.concatenate(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Preview the skeleton voice effects")
    ap.add_argument("wav", type=Path, help="16-bit mono WAV (e.g. greetings/family/greet_01.wav)")
    ap.add_argument("--pitch", type=float, help="semitones (negative = deeper)")
    ap.add_argument("--reverb", type=float, help="0..1 wet level")
    ap.add_argument("--drive", type=float, help="distortion drive dB (0 = off)")
    ap.add_argument("--gain", type=float, help="output gain dB")
    ap.add_argument("--compare", action="store_true", help="play dry first, then with FX")
    ap.add_argument("--out", type=Path, help="write result to this WAV")
    ap.add_argument("--no-play", action="store_true")
    a = ap.parse_args()

    cfg = load_config()
    overrides = {}
    if a.pitch is not None:
        overrides["fx_pitch"] = a.pitch
    if a.reverb is not None:
        overrides["fx_reverb"] = a.reverb
    if a.drive is not None:
        overrides["fx_drive_db"] = a.drive
    if a.gain is not None:
        overrides["fx_gain_db"] = a.gain
    cfg = replace(cfg, fx_enabled=True, **overrides)
    print(f"pitch={cfg.fx_pitch} reverb={cfg.fx_reverb} drive={cfg.fx_drive_db} gain={cfg.fx_gain_db}")

    pcm, rate = read_wav(a.wav)
    wet = render(cfg, pcm, rate)
    if a.out:
        write_wav(a.out, (np.clip(wet, -1, 1) * 32767).astype("<i2").tobytes(), P.DEVICE_RATE)
        print(f"wrote {a.out}")
    if not a.no_play:
        import sounddevice as sd

        if a.compare:
            dry = render(replace(cfg, fx_enabled=False), pcm, rate)
            print("dry...")
            sd.play(dry, P.DEVICE_RATE, blocking=True)
        print("with FX...")
        sd.play(wet, P.DEVICE_RATE, blocking=True)


if __name__ == "__main__":
    main()
