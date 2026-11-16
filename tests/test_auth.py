"""Device WebSocket token check (no hardware). Run:  python -m pytest tests/test_auth.py
or  python -m tests.test_auth"""
from __future__ import annotations

import asyncio

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from skeleton.server import make_auth_check

TOKEN = "s3cret-token"


async def _status(token_header: str | None, server_token: str = TOKEN) -> int:
    async def handler(ws):
        await ws.send("ok")

    async with serve(handler, "127.0.0.1", 0, process_request=make_auth_check(server_token)) as srv:
        port = srv.sockets[0].getsockname()[1]
        headers = {"Authorization": token_header} if token_header is not None else None
        try:
            async with connect(f"ws://127.0.0.1:{port}", additional_headers=headers) as ws:
                assert await ws.recv() == "ok"
                return 101
        except InvalidStatus as e:
            return e.response.status_code


def test_good_token() -> None:
    assert asyncio.run(_status(f"Bearer {TOKEN}")) == 101


def test_bearer_scheme_case_insensitive() -> None:
    assert asyncio.run(_status(f"bearer {TOKEN}")) == 101


def test_missing_token() -> None:
    assert asyncio.run(_status(None)) == 401


def test_wrong_token() -> None:
    assert asyncio.run(_status("Bearer nope")) == 401


def test_wrong_scheme() -> None:
    assert asyncio.run(_status(f"Basic {TOKEN}")) == 401


def test_empty_server_token_disables_auth() -> None:
    assert asyncio.run(_status(None, server_token="")) == 101


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
