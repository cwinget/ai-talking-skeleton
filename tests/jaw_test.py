"""Jaw + LED brightness test (no hardware): a fake BODY device answers jaw commands
that arrive through the admin HTTP API. Run:  python -m tests.jaw_test"""
from __future__ import annotations

import asyncio
import json
import os

os.environ.update({"BRAIN": "echo", "GEMINI_API_KEY": "", "PORT": "8797", "ADMIN_PORT": "8897", "DEVICE_TOKEN": "",
                   "GREETINGS_DIR": "/tmp/skeleton-jaw-greetings",
                   "SETTINGS_FILE": "/tmp/skeleton-jaw-settings.json"})

import aiohttp  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from skeleton.config import load_config  # noqa: E402
from skeleton.server import Server  # noqa: E402

API = "http://127.0.0.1:8897/api"


async def fake_body(received: list[dict], ready: asyncio.Event) -> None:
    jaw = {"closed": 90.0, "open": 120.0, "saved": False}
    leds = {"eyes": 0.5, "mouth": 0.5, "saved": False}
    async with connect("ws://127.0.0.1:8797") as ws:
        await ws.send(json.dumps({"type": "hello", "role": "body", "device": "fake-body"}))
        ready.set()
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            m = json.loads(raw)
            if m["type"].startswith("led_"):
                received.append(m)
                if m["type"] == "led_config":
                    leds = ({"eyes": 0.5, "mouth": 0.5, "saved": False} if m.get("reset") else
                            {"eyes": m.get("eyes", leds["eyes"]), "mouth": m.get("mouth", leds["mouth"]),
                             "saved": m.get("save", True)})
                await ws.send(json.dumps({"type": "led_config", **leds}))
                continue
            if not m["type"].startswith("jaw_"):
                continue
            received.append(m)
            if m["type"] == "jaw_config":
                if m.get("reset"):
                    jaw = {"closed": 90.0, "open": 120.0, "saved": False}
                else:
                    jaw = {"closed": m.get("closed", jaw["closed"]), "open": m.get("open", jaw["open"]),
                           "saved": m.get("save", True)}
            await ws.send(json.dumps({"type": "jaw_config", **jaw}))


async def main() -> None:
    server = Server(load_config())
    srv = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)
    try:
        async with aiohttp.ClientSession() as http:
            # no body connected -> clear error
            r = await http.get(f"{API}/jaw")
            assert r.status == 400 and "no body device" in (await r.json())["error"], await r.text()
            r = await http.get(f"{API}/leds")
            assert r.status == 400 and "no body device" in (await r.json())["error"], await r.text()

            received: list[dict] = []
            ready = asyncio.Event()
            body = asyncio.create_task(fake_body(received, ready))
            await ready.wait()
            await asyncio.sleep(0.2)

            r = await http.get(f"{API}/jaw")
            assert (await r.json())["jaw"]["closed"] == 90.0
            assert received[-1] == {"type": "jaw_get"}

            r = await http.post(f"{API}/jaw/config", json={"closed": 92, "open": 118})
            d = await r.json()
            assert r.status == 200 and d["jaw"] == {"closed": 92.0, "open": 118.0, "saved": True}, d
            assert received[-1] == {"type": "jaw_config", "save": True, "closed": 92.0, "open": 118.0}

            r = await http.post(f"{API}/jaw/config", json={"closed": 94, "save": False})
            assert (await r.json())["jaw"]["saved"] is False
            assert received[-1] == {"type": "jaw_config", "save": False, "closed": 94.0}

            r = await http.post(f"{API}/jaw/test", json={"action": "sweep", "count": 5})
            assert r.status == 200 and received[-1] == {"type": "jaw_test", "action": "sweep", "count": 5}
            r = await http.post(f"{API}/jaw/test", json={"action": "hold", "deg": 105})
            assert received[-1] == {"type": "jaw_test", "action": "hold", "ms": 3000, "deg": 105.0}
            r = await http.post(f"{API}/jaw/test", json={"action": "open"})
            assert received[-1] == {"type": "jaw_test", "action": "open", "ms": 3000}

            r = await http.post(f"{API}/jaw/config", json={"reset": True})
            assert (await r.json())["jaw"]["closed"] == 90.0 and received[-1]["reset"] is True

            # bad requests never reach the body
            n = len(received)
            for path, bad in [("config", {"closed": 200}), ("config", {"closed": "x"}),
                              ("config", {}), ("test", {"action": "dance"}),
                              ("test", {"action": "sweep", "count": 99}),
                              ("test", {"action": "hold"}), ("test", {"action": "hold", "deg": -1})]:
                r = await http.post(f"{API}/jaw/{path}", json=bad)
                assert r.status == 400, (path, bad, r.status)
            assert len(received) == n

            # LED brightness
            r = await http.get(f"{API}/leds")
            assert (await r.json())["leds"] == {"eyes": 0.5, "mouth": 0.5, "saved": False}
            assert received[-1] == {"type": "led_get"}
            r = await http.post(f"{API}/leds/config", json={"eyes": 0.35})
            assert (await r.json())["leds"] == {"eyes": 0.35, "mouth": 0.5, "saved": True}
            assert received[-1] == {"type": "led_config", "save": True, "eyes": 0.35}
            r = await http.post(f"{API}/leds/config", json={"eyes": 0.2, "mouth": 0.6, "save": False})
            assert (await r.json())["leds"]["saved"] is False
            assert received[-1] == {"type": "led_config", "save": False, "eyes": 0.2, "mouth": 0.6}
            await http.post(f"{API}/leds/test", json={"target": "eyes", "level": 0.3, "ms": 10000})
            assert received[-1] == {"type": "led_test", "target": "eyes", "level": 0.3, "ms": 10000}
            await http.post(f"{API}/leds/test", json={})
            assert received[-1] == {"type": "led_test", "target": "both", "level": 1.0, "ms": 3000}
            await http.post(f"{API}/leds/test", json={"action": "stop"})
            assert received[-1] == {"type": "led_test", "action": "stop"}
            r = await http.post(f"{API}/leds/config", json={"reset": True})
            assert (await r.json())["leds"]["eyes"] == 0.5 and received[-1]["reset"] is True
            n = len(received)
            for path, bad in [("config", {"eyes": 1.5}), ("config", {"eyes": "x"}), ("config", {}),
                              ("test", {"target": "nose"}), ("test", {"level": -1}),
                              ("test", {"ms": 50}), ("test", {"ms": 70000})]:
                r = await http.post(f"{API}/leds/{path}", json=bad)
                assert r.status == 400, (path, bad, r.status)
            assert len(received) == n
            body.cancel()
        print("JAW TEST PASSED")
    finally:
        srv.cancel()
        try:
            await srv  # let the server shut down cleanly, or asyncio.run() hangs on exit
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
