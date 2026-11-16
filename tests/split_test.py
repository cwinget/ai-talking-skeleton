"""Two-device test (echo brain, no hardware): a fake AUDIO device and a fake
BODY device. Checks routing (trigger from body, audio to audio device, capture
to body) and that the body gets mouth levels lined up with the audio.
Run:  python -m tests.split_test"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time

os.environ.update({"VISION_ENABLED": "true", "BRAIN": "echo", "GEMINI_API_KEY": "", "SILENCE_TIMEOUT_S": "3",
                   "COOLDOWN_S": "1", "DEVICE_TOKEN": "", "MAX_TURNS": "1", "PORT": "8798", "MOUTH_DELAY_MS": "100",
                   "ADMIN_PORT": "8898", "GREETINGS_DIR": "/tmp/skeleton-split-greetings",
                   "SETTINGS_FILE": "/tmp/skeleton-split-settings.json"})

import numpy as np  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from skeleton import protocol as P  # noqa: E402
from skeleton.config import load_config  # noqa: E402
from skeleton.server import Server  # noqa: E402

URL = "ws://127.0.0.1:8798"


def tone(seconds: float, amp: float) -> list[bytes]:
    t = np.arange(int(seconds * P.DEVICE_RATE)) / P.DEVICE_RATE
    x = (amp * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()
    return [x[i : i + P.FRAME_BYTES] for i in range(0, len(x), P.FRAME_BYTES)]


async def audio_device(stats: dict) -> None:
    async with connect(URL) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "audio", "device": "fake-audio"}))
        plays = 0
        while True:
            msg = await asyncio.wait_for(ws.recv(), 10)
            if isinstance(msg, bytes):
                env, _ = P.unpack_audio(msg)
                stats["audio_frames"] += 1
                stats["audio_times"].append((time.monotonic(), env))
                continue
            m = json.loads(msg)
            if m["type"] == "capture":
                stats["audio_got_capture"] = True
            elif m["type"] == "play_end":
                await asyncio.sleep(0.15)
                await ws.send(json.dumps({"type": "playback_done", "id": m["id"]}))
                plays += 1
                if plays == 1:
                    await asyncio.sleep(0.2)
                    for f in tone(1.0, 0.3) + tone(1.2, 0.0):
                        await ws.send(f)
                        await asyncio.sleep(0.02)
            elif m["type"] == "state" and m["state"] == "idle":
                stats["plays"] = plays
                return


async def body_device(stats: dict) -> None:
    async with connect(URL) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "body", "device": "fake-body"}))
        await asyncio.sleep(0.5)  # let the audio device connect too
        await ws.send(json.dumps({"type": "presence", "present": True}))
        while True:
            msg = await asyncio.wait_for(ws.recv(), 10)
            if isinstance(msg, bytes):
                assert msg[0] == P.MSG_MOUTH, "body should only get mouth frames"
                stats["mouth_frames"] += 1
                stats["mouth_times"].append((time.monotonic(), msg[1]))
                continue
            m = json.loads(msg)
            if m["type"] == "capture":
                stats["body_got_capture"] = True
                for i in range(m["count"]):
                    await ws.send(json.dumps({"type": "image", "seq": i,
                                              "jpeg_b64": base64.b64encode(b"x").decode()}))
            elif m["type"] == "state" and m["state"] == "idle":
                return


def mouth_offsets(stats) -> list[float]:
    """For the greeting (first utterance): a device starts playing when frame 0
    arrives and plays one 20 ms frame after another, so frame k plays at
    t_first + k * 20 ms. Return how far after that each mouth level arrived."""
    t_first = stats["audio_times"][0][0]
    n = min(len(stats["mouth_times"]), 60)
    return [stats["mouth_times"][k][0] - (t_first + k * P.FRAME_MS / 1000) for k in range(n)]


async def main() -> None:
    server = Server(load_config())
    srv = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)
    stats = {"audio_frames": 0, "mouth_frames": 0, "audio_times": [], "mouth_times": [],
             "audio_got_capture": False, "body_got_capture": False, "plays": 0}
    try:
        await asyncio.gather(audio_device(stats), body_device(stats))
        offs = mouth_offsets(stats)
        med = float(np.median(offs))
        print(f"audio frames: {stats['audio_frames']}  mouth frames: {stats['mouth_frames']}")
        print(f"mouth arrives {med * 1000:.0f} ms after its frame plays "
              f"(MOUTH_DELAY_MS=100 expected), spread {np.ptp(offs) * 1000:.0f} ms")
        assert stats["plays"] >= 3
        assert stats["body_got_capture"] and not stats["audio_got_capture"]
        assert abs(stats["mouth_frames"] - stats["audio_frames"]) <= stats["plays"] + 5
        assert 0.07 < med < 0.14, med
        assert np.ptp(offs) < 0.05
        print("SPLIT TEST PASSED")
    finally:
        srv.cancel()
        try:
            await srv  # let the server shut down cleanly, or asyncio.run() hangs on exit
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    import logging

    logging.basicConfig(level="INFO", format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    asyncio.run(main())
