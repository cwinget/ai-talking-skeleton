"""Aux (presence-only) clients and camera rotation, no hardware. Run: python -m tests.test_aux"""
from __future__ import annotations

import asyncio
import io
import json
import os

os.environ.update({"BRAIN": "echo", "GEMINI_API_KEY": "", "PORT": "8796", "ADMIN_PORT": "8896",
                   "DEVICE_TOKEN": "", "CAMERA_ROTATE_180": "1", "COOLDOWN_S": "1",
                   "GREETINGS_DIR": "/tmp/skeleton-aux-greetings",
                   "SETTINGS_FILE": "/tmp/skeleton-aux-settings.json",
                   "PHOTOS_DIR": "/tmp/skeleton-aux-photos"})

from PIL import Image  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from skeleton.config import load_config  # noqa: E402
from skeleton.server import Server, rotate_jpeg_180  # noqa: E402

URL = "ws://127.0.0.1:8796"


def _jpeg(top_left_red: bool = True) -> bytes:
    img = Image.new("RGB", (64, 32), "blue")
    img.paste("red", (0, 0, 16, 8))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=95)
    return out.getvalue()


def test_rotate() -> None:
    rotated = Image.open(io.BytesIO(rotate_jpeg_180(_jpeg()))).convert("RGB")
    assert rotated.size == (64, 32)
    r, g, b = rotated.getpixel((4, 4))
    assert b > r, "top-left should now be blue"
    r, g, b = rotated.getpixel((60, 28))
    assert r > b, "bottom-right should now be red"


async def recv_presence(ws, timeout: float = 2.0) -> bool:
    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
    assert msg["type"] == "presence", msg
    return msg["present"]


async def e2e() -> None:
    server = Server(load_config())
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.5)
    try:
        hello = lambda role, dev: json.dumps({"type": "hello", "role": role, "device": dev})  # noqa: E731
        async with connect(URL) as body, connect(URL) as pumpkin, connect(URL) as pumpkin2:
            await body.send(hello("body", "body1"))
            await pumpkin.send(hello("aux", "pumpkin"))
            await pumpkin2.send(hello("aux", "ghost"))
            # newcomers learn the current state (nobody there)
            assert await recv_presence(pumpkin) is False
            assert await recv_presence(pumpkin2) is False

            await body.send(json.dumps({"type": "presence", "present": True}))
            assert await recv_presence(pumpkin) is True
            assert await recv_presence(pumpkin2) is True
            await body.send(json.dumps({"type": "presence", "present": True}))  # duplicate: no resend
            await body.send(json.dumps({"type": "presence", "present": False}))
            assert await recv_presence(pumpkin) is False
            assert await recv_presence(pumpkin2) is False

            # an aux client can't trigger anything or disturb the real devices
            hub = server.hub
            await pumpkin.send(json.dumps({"type": "presence", "present": True}))
            await pumpkin.send(json.dumps({"type": "image", "seq": 0, "jpeg_b64": "AAAA"}))
            await asyncio.sleep(0.3)
            assert hub.present is False and hub.conv_task is None and hub.body.name.startswith("body1")
            assert hub.audio is None and len(hub.aux) == 2

            # admin UI "Someone arrived/left" reaches aux even with no body or audio device
            import aiohttp
            async with aiohttp.ClientSession() as http:
                for flag in (True, False):
                    await http.post("http://127.0.0.1:8896/api/presence", json={"present": flag})
                    assert await recv_presence(pumpkin) is flag
                    assert await recv_presence(pumpkin2) is flag

            # motion sensor toggle: the body's reports are ignored while it's off
            api = "http://127.0.0.1:8896/api"
            async with aiohttp.ClientSession() as http:
                st = await (await http.get(f"{api}/status")).json()
                assert st["sensor_enabled"] is True
                r = await http.post(f"{api}/sensor", json={"enabled": "no"})
                assert r.status == 400
                await http.post(f"{api}/sensor", json={"enabled": False})
                assert (await (await http.get(f"{api}/status")).json())["sensor_enabled"] is False
                await body.send(json.dumps({"type": "presence", "present": True}))
                await body.send(json.dumps({"type": "trigger"}))
                await asyncio.sleep(0.3)
                assert hub.present is False
                try:
                    await recv_presence(pumpkin, 0.4)
                    raise AssertionError("aux notified while sensor disabled")
                except asyncio.TimeoutError:
                    pass
                # manual UI buttons still work while the sensor is off
                await http.post(f"{api}/presence", json={"present": True})
                assert await recv_presence(pumpkin) is True
                await http.post(f"{api}/presence", json={"present": False})
                assert await recv_presence(pumpkin) is False
                assert await recv_presence(pumpkin2) is True
                assert await recv_presence(pumpkin2) is False
                await http.post(f"{api}/sensor", json={"enabled": True})
                await body.send(json.dumps({"type": "presence", "present": True}))
                assert await recv_presence(pumpkin) is True
                await body.send(json.dumps({"type": "presence", "present": False}))
                assert await recv_presence(pumpkin) is False
                assert await recv_presence(pumpkin2) is True
                assert await recv_presence(pumpkin2) is False

            # a rotated camera frame reaches the saved photo and the admin preview
            import base64
            await body.send(json.dumps({"type": "image", "seq": 0,
                                        "jpeg_b64": base64.b64encode(_jpeg()).decode()}))
            await asyncio.sleep(0.3)
            ts, jpeg = hub.recent_photos[-1]
            assert Image.open(io.BytesIO(jpeg)).convert("RGB").getpixel((4, 4))[2] > 100

            # radar board disappears while someone is "present": aux is told they left
            await body.send(json.dumps({"type": "presence", "present": True}))
            assert await recv_presence(pumpkin) is True
            await body.close()
            assert await recv_presence(pumpkin) is False  # body gone
            await pumpkin2.close()
            await asyncio.sleep(0.2)
            assert [c.name.split("@")[0] for c in server.hub.aux] == ["pumpkin"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    test_rotate()
    print("ok rotate")
    asyncio.run(e2e())
    print("ok aux e2e")
