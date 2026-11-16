"""Random-phrases mode, no hardware or API key. Run: python -m tests.test_chatter"""
from __future__ import annotations

import asyncio
import json
import os
import shutil

for d in ("greetings", "photos"):
    shutil.rmtree(f"/tmp/skeleton-chat-{d}", ignore_errors=True)
os.environ.update({"BRAIN": "echo", "GEMINI_API_KEY": "", "PORT": "8795", "ADMIN_PORT": "8895",
                   "DEVICE_TOKEN": "", "CAMERA_ROTATE_180": "0", "COOLDOWN_S": "1",
                   "CHATTER_INTERVAL_S": "2", "SILENCE_TIMEOUT_S": "3", "MAX_TURNS": "1",
                   "GREETINGS_DIR": "/tmp/skeleton-chat-greetings",
                   "SETTINGS_FILE": "/tmp/skeleton-chat-settings.json",
                   "PHOTOS_DIR": "/tmp/skeleton-chat-photos", "PERSONA_MODE": "family"})
os.environ.pop("MODE_FILE", None)
os.environ["MODE_FILE"] = "/tmp/skeleton-chat-mode.txt"

import aiohttp  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from skeleton.config import load_config  # noqa: E402
from skeleton.server import Server  # noqa: E402

API = "http://127.0.0.1:8895/api"


async def audio_device(events: list[str]) -> None:
    async with connect("ws://127.0.0.1:8795") as ws:
        await ws.send(json.dumps({"type": "hello", "role": "audio", "device": "fake-audio"}))
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            m = json.loads(raw)
            events.append(m["type"] + (":" + m["state"] if m["type"] == "state" else ""))
            if m["type"] == "play_end":
                await ws.send(json.dumps({"type": "playback_done", "id": m["id"]}))


async def main() -> None:
    server = Server(load_config())
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.8)
    events: list[str] = []
    dev = asyncio.create_task(audio_device(events))
    try:
        async with aiohttp.ClientSession() as http:
            async def get():
                return await (await http.get(f"{API}/chatter")).json()

            c = await get()
            assert c["enabled"] is False and c["mode"] == "family"
            assert len(c["phrases"]) == 10, c  # seeded defaults, no API key needed for the list
            assert os.path.exists("/tmp/skeleton-chat-greetings/family/phrases/lines.txt")
            assert os.path.exists("/tmp/skeleton-chat-greetings/scary/phrases/lines.txt")

            # nothing is said while off
            await asyncio.sleep(1.5)
            assert "play_start" not in events

            # add a phrase: validated, joins both modes, no duplicates
            r = await http.post(f"{API}/chatter/phrases", json={"text": "  Boo   hoo!  "})
            assert r.status == 200 and (await r.json())["phrases"][-1]["text"] == "Boo hoo!"
            assert (await http.post(f"{API}/chatter/phrases", json={"text": "boo hoo!"})).status == 400
            assert (await http.post(f"{API}/chatter/phrases", json={"text": "  "})).status == 400
            assert (await http.post(f"{API}/chatter/phrases", json={"text": "x" * 300})).status == 400
            assert "Boo hoo!" in open("/tmp/skeleton-chat-greetings/scary/phrases/lines.txt").read()

            # on: speaks repeatedly, with nobody present and no sensor involved
            assert (await http.post(f"{API}/chatter", json={"enabled": "yes"})).status == 400
            assert (await (await http.post(f"{API}/chatter", json={"enabled": True})).json())["enabled"]
            await asyncio.sleep(6.5)
            plays = events.count("play_start")
            assert plays >= 2, f"expected repeated phrases, got {plays}: {events}"

            # a visitor arriving mid-phrase cuts it off (device told to flush) and gets their greeting
            for _ in range(200):
                if (await get())["speaking"]:
                    break
                await asyncio.sleep(0.03)
            else:
                raise AssertionError("never caught a phrase in progress")
            assert "stop" not in events
            await http.post(f"{API}/presence", json={"present": True})
            await asyncio.sleep(0.5)
            assert "stop" in events, events
            assert (await (await http.get(f"{API}/status")).json())["conversation_active"]
            await asyncio.sleep(1.5)  # chatter stays quiet during the conversation
            assert (await get())["speaking"] is False

            # off: stops
            await http.post(f"{API}/presence", json={"present": False})
            await asyncio.sleep(5)
            await http.post(f"{API}/chatter", json={"enabled": False})
            await asyncio.sleep(0.5)
            n = events.count("play_start")
            await asyncio.sleep(3)
            assert events.count("play_start") == n, "spoke after being switched off"
        print("CHATTER TEST PASSED")
    finally:
        dev.cancel()
        task.cancel()
        await asyncio.gather(dev, task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
