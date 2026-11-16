"""Headless end-to-end test of the protocol with the echo brain (no API key,
no audio hardware). Run:  python -m tests.smoke_test
Plays the role of the device: triggers a visitor, confirms playback, "speaks"
a synthetic tone, and checks that the skeleton answers."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time

os.environ["BRAIN"] = "echo"
os.environ["GEMINI_API_KEY"] = ""
os.environ["SILENCE_TIMEOUT_S"] = "3"
os.environ["COOLDOWN_S"] = "1"
os.environ["MAX_TURNS"] = "1"
os.environ["PORT"] = "8799"
os.environ["ADMIN_PORT"] = "8899"
os.environ["CAMERA_ROTATE_180"] = "0"  # smoke frames aren't real JPEGs
os.environ["DEVICE_TOKEN"] = ""  # these tests exercise the protocol, not auth
os.environ["VISION_ENABLED"] = "true"  # exercise the capture path (off by default)
os.environ["GREETINGS_DIR"] = "/tmp/skeleton-smoke-greetings"
os.environ["SETTINGS_FILE"] = "/tmp/skeleton-smoke-settings.json"

import numpy as np  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from skeleton import protocol as P  # noqa: E402
from skeleton.config import load_config  # noqa: E402
from skeleton.server import Server  # noqa: E402


def tone(seconds: float, amp: float) -> list[bytes]:
    t = np.arange(int(seconds * P.DEVICE_RATE)) / P.DEVICE_RATE
    x = (amp * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()
    return [x[i : i + P.FRAME_BYTES] for i in range(0, len(x), P.FRAME_BYTES)]


async def device(log: list[str]) -> None:
    async with connect("ws://127.0.0.1:8799") as ws:
        await ws.send(json.dumps({"type": "hello", "device": "smoke"}))
        await ws.send(json.dumps({"type": "presence", "present": True}))
        frames_per_play: dict[int, int] = {}
        current = None
        plays_done = 0
        spoke = False
        states = []
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), 5)
            except asyncio.TimeoutError:
                break
            if isinstance(msg, bytes):
                env, pcm = P.unpack_audio(msg)
                assert len(pcm) == P.FRAME_BYTES, len(pcm)
                frames_per_play[current] = frames_per_play.get(current, 0) + 1
                continue
            m = json.loads(msg)
            t = m["type"]
            if t == "capture":
                for i in range(m["count"]):
                    await ws.send(json.dumps({"type": "image", "seq": i,
                                              "jpeg_b64": base64.b64encode(b"\xff\xd8fake").decode()}))
            elif t == "play_start":
                current = m["id"]
            elif t == "play_end":
                await asyncio.sleep(0.2)
                await ws.send(json.dumps({"type": "playback_done", "id": m["id"]}))
                plays_done += 1
                log.append(f"play {m['id']}: {frames_per_play.get(m['id'], 0) * 20} ms")
                if plays_done == 1 and not spoke:  # greeting finished: visitor talks
                    spoke = True
                    await asyncio.sleep(0.3)
                    for f in tone(1.0, 0.3) + tone(1.2, 0.0):
                        await ws.send(f)
                        await asyncio.sleep(0.02)
            elif t == "state":
                states.append(m["state"])
                if m["state"] == "idle":
                    break
        log.append(f"states: {states}")
        assert plays_done >= 3, f"expected greeting + echo reply + goodbye, got {plays_done}"
        assert states[-1] == "idle"


async def main() -> None:
    cfg = load_config()
    server = Server(cfg)
    srv_task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)
    log: list[str] = []
    try:
        await device(log)
        print("\n".join(log))
        print("SMOKE TEST PASSED")
    finally:
        srv_task.cancel()
        try:
            await srv_task  # let the server shut down cleanly, or asyncio.run() hangs on exit
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    import logging

    logging.basicConfig(level="INFO", format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    asyncio.run(main())
