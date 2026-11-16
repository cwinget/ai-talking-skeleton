"""Admin API blocks cross-site browser POSTs (Origin != Host). Run: python -m tests.test_admin_origin"""
from __future__ import annotations

import asyncio
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="skeleton-origin-")
os.environ.update({"BRAIN": "echo", "GEMINI_API_KEY": "", "DEVICE_TOKEN": "",
                   "PORT": "8797", "ADMIN_PORT": "8897",
                   "GREETINGS_DIR": f"{_tmp}/greetings", "SETTINGS_FILE": f"{_tmp}/settings.json",
                   "MODE_FILE": f"{_tmp}/mode.txt"})

import aiohttp  # noqa: E402

from skeleton.config import load_config  # noqa: E402
from skeleton.server import Server  # noqa: E402

URL = "http://127.0.0.1:8897/api/mode"


async def main() -> None:
    srv = asyncio.create_task(Server(load_config()).run())
    await asyncio.sleep(1.0)
    try:
        async with aiohttp.ClientSession() as http:
            r = await http.post(URL, json={"mode": "auto"})  # curl/script: no Origin
            assert r.status == 200, r.status
            r = await http.post(URL, json={"mode": "auto"}, headers={"Origin": "http://127.0.0.1:8897"})
            assert r.status == 200, r.status  # the admin page itself
            r = await http.post(URL, data='{"mode":"scary"}',
                                headers={"Origin": "http://evil.example", "Content-Type": "text/plain"})
            assert r.status == 403, r.status
            r = await http.get(URL, headers={"Origin": "http://evil.example"})
            assert r.status == 200, r.status  # reads are not blocked
            assert (await (await http.get(URL)).json())["requested"] == "auto"
        print("ADMIN ORIGIN TEST PASSED")
    finally:
        srv.cancel()
        try:
            await srv
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
