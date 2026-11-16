"""Costume description: collect a few JPEG frames from the device, ask a fast
vision model for a structured description. Images are kept in memory only."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .config import Config
from .prompts import VISION_PROMPT, Scene

log = logging.getLogger("skeleton.vision")


class Vision:
    CAPTURE_WINDOW_S = 2.5  # max time to wait for frames to arrive from the device

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = None
        if cfg.vision_enabled and cfg.has_key:
            from google import genai

            self.client = genai.Client(api_key=cfg.api_key)

    async def describe_from_queue(self, image_q: asyncio.Queue, count: int) -> Scene | None:
        images: list[bytes] = []
        deadline = time.monotonic() + self.CAPTURE_WINDOW_S
        while len(images) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                images.append(await asyncio.wait_for(image_q.get(), remaining))
            except asyncio.TimeoutError:
                break
        if not images:
            log.info("no camera frames received")
            return None
        if self.client is None:
            log.info("got %d frame(s); vision disabled or no API key", len(images))
            return None
        return await self._describe(images)

    async def _describe(self, images: list[bytes]) -> Scene | None:
        from google.genai import types

        t0 = time.monotonic()
        parts = [types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in images]
        resp = await self.client.aio.models.generate_content(
            model=self.cfg.vision_model,
            contents=[*parts, VISION_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Scene,
                temperature=0.2,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        scene = resp.parsed if isinstance(resp.parsed, Scene) else Scene(**json.loads(resp.text))
        log.info("vision (%.2fs, %d frames): %s", time.monotonic() - t0, len(images), scene)
        return scene
