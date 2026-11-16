"""Pre-recorded greetings, generated with the SAME Live model + voice so the
greeting and the live replies sound like the same skeleton. Stored raw (no FX);
FX is applied at playback so tuning FX affects greetings too.

Each persona mode has its own folder: greetings/family/, greetings/scary/.

    python -m skeleton.greetings                    # (re)generate both modes
    python -m skeleton.greetings --mode scary       # just one mode
    python -m skeleton.greetings --mode family --only 2 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Config, load_config
from .modes import cfg_for_mode
from .prompts import MODES

log = logging.getLogger("skeleton.greetings")


@dataclass
class Greeting:
    text: str
    pcm: bytes
    rate: int


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{path}: must be 16-bit mono WAV")
        return w.readframes(w.getnframes()), w.getframerate()


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def lines_file(mcfg: Config, mode: str) -> Path:
    """mcfg = cfg_for_mode(cfg, mode): its greetings_dir is the mode's folder."""
    p = mcfg.greetings_dir / "lines.txt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {mode} greetings: one per line. Lines starting with # are ignored.\n"
                     + "\n".join(MODES[mode].greetings) + "\n")
    return p


def read_lines(mcfg: Config, mode: str) -> list[str]:
    return [
        ln.strip()
        for ln in lines_file(mcfg, mode).read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def trim_silence(pcm: bytes, rate: int, thresh: float = 0.015) -> bytes:
    """Strip leading/trailing silence (keeps a little padding)."""
    x = np.frombuffer(pcm, dtype="<i2")
    loud = np.flatnonzero(np.abs(x) > thresh * 32768)
    if loud.size == 0:
        return pcm
    start = max(0, loud[0] - int(0.05 * rate))
    end = min(x.size, loud[-1] + int(0.15 * rate))
    return x[start:end].tobytes()


def _norm(t: str) -> str:
    return re.sub(r"[^a-z]", "", t.lower())


async def synthesize_line(cfg: Config, mode: str, line: str) -> tuple[bytes, int, str]:
    """Render `line` verbatim in this mode's voice via a one-shot Live session
    (the same trick ensure_greetings uses for greeting clips). Returns
    (pcm, rate, what the model's own transcript heard itself say)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=cfg.api_key)
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=MODES[mode].actor,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=cfg.voice)
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    audio = bytearray()
    heard: list[str] = []
    async with client.aio.live.connect(model=cfg.live_model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=f'Perform this line: "{line}"')]),
            turn_complete=True,
        )
        async for msg in session.receive():
            sc = msg.server_content
            if not sc:
                continue
            if sc.model_turn and sc.model_turn.parts:
                for p in sc.model_turn.parts:
                    if p.inline_data and p.inline_data.data:
                        audio += p.inline_data.data
            if sc.output_transcription and sc.output_transcription.text:
                heard.append(sc.output_transcription.text)
            if sc.turn_complete:
                break
    return trim_silence(bytes(audio), 24_000), 24_000, "".join(heard).strip()


async def generate(mcfg: Config, mode: str, only: set[int] | None = None) -> None:
    cfg = mcfg
    meta_path = cfg.greetings_dir / "greetings.json"
    existing = {e["file"]: e for e in json.loads(meta_path.read_text())} if meta_path.exists() else {}
    out: list[dict] = []
    log.info("[%s] generating greetings with voice %s", mode, cfg.voice)
    for i, line in enumerate(read_lines(cfg, mode), start=1):
        fname = f"greet_{i:02d}.wav"
        if only and i not in only and fname in existing:
            out.append(existing[fname])
            continue
        # One session per line keeps earlier lines from influencing later ones.
        pcm, rate, spoken = await synthesize_line(cfg, mode, line)
        write_wav(cfg.greetings_dir / fname, pcm, rate)
        log.info("%s (%.1fs): %s", fname, len(pcm) / (rate * 2), spoken or line)
        if spoken and _norm(spoken) != _norm(line):
            log.warning("  %s may not match the script. Listen to it; regenerate with: "
                        "python -m skeleton.greetings --mode %s --only %d", fname, mode, i)
        out.append({"file": fname, "text": line, "heard": spoken})
    meta_path.write_text(json.dumps(out, indent=2))
    log.info("wrote %d greetings to %s", len(out), cfg.greetings_dir)


def _placeholder(cfg: Config) -> list[Greeting]:
    rate = 16_000
    t = np.arange(int(1.2 * rate)) / rate
    f = 110 + 20 * np.sin(2 * np.pi * 3 * t)
    x = 0.35 * np.sin(2 * np.pi * np.cumsum(f) / rate) * np.minimum(1, (1.2 - t) * 4)
    return [Greeting("(placeholder greeting tone)", (x * 32767).astype("<i2").tobytes(), rate)]


def load_greetings(mcfg: Config) -> list[Greeting]:
    cfg = mcfg
    meta = cfg.greetings_dir / "greetings.json"
    if not meta.exists():
        log.warning("No greetings generated yet: using a placeholder tone")
        return _placeholder(cfg)
    items = []
    for entry in json.loads(meta.read_text()):
        pcm, rate = read_wav(cfg.greetings_dir / entry["file"])
        if pcm:
            items.append(Greeting(entry["text"], pcm, rate))
    return items or _placeholder(cfg)


def _migrate_legacy(cfg: Config) -> None:
    """Before modes existed, greetings lived directly in greetings/. Move them to
    greetings/family/ so they aren't regenerated."""
    root, fam = cfg.greetings_dir, cfg.greetings_dir / "family"
    if (root / "greetings.json").exists() and not (fam / "greetings.json").exists():
        fam.mkdir(parents=True, exist_ok=True)
        for f in list(root.glob("greet_*.wav")) + [root / "greetings.json", root / "lines.txt"]:
            if f.exists():
                shutil.move(str(f), fam / f.name)
        log.info("moved existing greetings into %s", fam)


async def ensure_greetings(cfg: Config) -> dict[str, list[Greeting]]:
    _migrate_legacy(cfg)
    out = {}
    for mode in MODES:
        mcfg = cfg_for_mode(cfg, mode)
        if not (mcfg.greetings_dir / "greetings.json").exists() and cfg.use_gemini:
            log.info("[%s] no greetings yet: generating them", mode)
            await generate(mcfg, mode)
        out[mode] = load_greetings(mcfg)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate greeting audio from greetings/<mode>/lines.txt")
    ap.add_argument("--mode", choices=[*MODES, "all"], default="all")
    ap.add_argument("--only", type=int, nargs="+", help="regenerate only these line numbers (1-based)")
    args = ap.parse_args()
    cfg = load_config()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(name)s: %(message)s")
    if not cfg.has_key:
        raise SystemExit("GEMINI_API_KEY is not set (see .env.example)")
    _migrate_legacy(cfg)
    modes = list(MODES) if args.mode == "all" else [args.mode]

    async def run():
        for mode in modes:
            mcfg = cfg_for_mode(cfg, mode)
            lines_file(mcfg, mode)
            await generate(mcfg, mode, set(args.only) if args.only else None)

    asyncio.run(run())


if __name__ == "__main__":
    main()
