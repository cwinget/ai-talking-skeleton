"""ambient: loop, volume, fade-out hand-off. Run: python -m tests.test_ambient"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("GEMINI_API_KEY", "")

from skeleton import protocol as P  # noqa: E402
from skeleton.ambient import Ambient, level_to_gain, list_files  # noqa: E402
from skeleton.config import load_config  # noqa: E402


class FakeHub:
    def __init__(self, cfg):
        self.env_cfg = cfg
        self.audio = object()
        self.announcing = False
        self.conv_task = None
        self.cooldown_until = 0.0
        self.chatter = SimpleNamespace(speaking=False)  # music waits while a random phrase plays
        self.sent: list = []

    async def send_audio_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def send_audio_json(self, obj: dict) -> None:
        self.sent.append(json.dumps(obj))


def amplitudes(sent) -> list[float]:
    out = []
    for m in sent:
        if isinstance(m, bytes):
            assert m[0] == P.MSG_AUDIO and m[1] == 0 and len(m) == 2 + P.FRAME_BYTES
            out.append(float(np.abs(np.frombuffer(m[2:], "<i2")).max()) / 32768)
    return out


async def main() -> None:
    from pedalboard.io import AudioFile

    tmp = Path(tempfile.mkdtemp())
    t = np.arange(44100) / 44100
    tone = (0.8 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    with AudioFile(str(tmp / "tone.mp3"), "w", 44100, 1) as f:
        f.write(tone[None, :])
    (tmp / "notes.txt").write_text("x")
    assert list_files(tmp) == ["tone.mp3"]

    cfg = replace(load_config(), ambient_dir=tmp, ambient_file="tone.mp3", ambient_volume=1.0,
                  settings_file=tmp / "settings.json")
    hub = FakeHub(cfg)
    amb = Ambient(hub)
    assert not amb.enabled and not amb.playing  # starts off

    assert level_to_gain(0) == 0 and level_to_gain(1) == 1 and level_to_gain(0.5) == 0.25
    try:
        amb.configure(file="../etc/passwd")
        assert False, "expected ValueError"
    except ValueError:
        pass

    amb.configure(enabled=True)
    amb.start()
    await asyncio.sleep(2.0)  # 1 s fade-in, then full
    assert amb.playing
    amps = amplitudes(hub.sent)
    assert len(amps) > 40 and amps[0] < 0.1 and max(amps) > 0.7, (len(amps), amps[:3], max(amps))
    assert len(amps) < 2.0 * 50 + 10  # paced in real time, not dumped

    # a conversation starting stops the supervisor from restarting it, and fade_out ends quietly
    hub.conv_task = SimpleNamespace(done=lambda: False)
    n = len(hub.sent)
    await amb.fade_out()
    assert not amb.playing
    tail = amplitudes(hub.sent[n:])
    assert 60 <= len(tail) <= 90, len(tail)  # ~1.5 s of frames
    assert tail == sorted(tail, reverse=True) or tail[-1] < 0.01
    assert tail[-1] < 0.01
    assert json.loads(hub.sent[-1]) == {"type": "stop"}
    await asyncio.sleep(0.6)
    assert not amb.playing  # still held off while the conversation runs

    # conversation over: comes back once the cooldown passes
    hub.conv_task = None
    await asyncio.sleep(0.6)
    assert amb.playing

    # disabling fades out and stays off
    amb.configure(enabled=False)
    await asyncio.sleep(2.5)
    assert not amb.playing and json.loads(hub.sent[-1]) == {"type": "stop"}

    # unreadable file turns itself off with an error instead of looping forever
    (tmp / "bad.mp3").write_bytes(b"not audio")
    amb.configure(file="bad.mp3", enabled=True)
    await asyncio.sleep(1.0)
    assert not amb.enabled and amb.error
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
