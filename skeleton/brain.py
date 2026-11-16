"""Conversation 'brains'. Both expose the same interface and push events onto
`self.events` as tuples:

    ("audio", pcm16_bytes)        model speech at self.out_rate, mono s16le
    ("model_text", str)           transcript fragment of what the model said
    ("user_text", str)            transcript fragment of what the visitor said
    ("turn_complete",)            model finished a reply
    ("error", Exception) / ("closed",)
"""
from __future__ import annotations

import asyncio
import logging

import numpy as np

from .config import Config

log = logging.getLogger("skeleton.brain")


class GeminiBrain:
    out_rate = 24_000  # Live API output is always 24 kHz

    def __init__(self, cfg: Config):
        from google import genai

        self.cfg = cfg
        self.client = genai.Client(api_key=cfg.api_key)
        self.events: asyncio.Queue = asyncio.Queue()
        self._cm = None
        self.session = None
        self._rx: asyncio.Task | None = None

    async def start(self, system_instruction: str) -> None:
        from google.genai import types

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=system_instruction,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.cfg.voice)
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    prefix_padding_ms=200,
                    silence_duration_ms=self.cfg.vad_silence_ms,
                )
            ),
        )
        self._cm = self.client.aio.live.connect(model=self.cfg.live_model, config=config)
        self.session = await self._cm.__aenter__()
        self._rx = asyncio.create_task(self._receive())
        log.info("Gemini Live session open (%s, voice=%s)", self.cfg.live_model, self.cfg.voice)

    async def _receive(self) -> None:
        try:
            while True:
                got_any = False
                async for msg in self.session.receive():
                    got_any = True
                    sc = msg.server_content
                    if sc is None:
                        continue
                    if sc.model_turn and sc.model_turn.parts:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                self.events.put_nowait(("audio", part.inline_data.data))
                    if sc.input_transcription and sc.input_transcription.text:
                        self.events.put_nowait(("user_text", sc.input_transcription.text))
                    if sc.output_transcription and sc.output_transcription.text:
                        self.events.put_nowait(("model_text", sc.output_transcription.text))
                    if sc.turn_complete:
                        self.events.put_nowait(("turn_complete",))
                if not got_any:  # connection closed
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Live receive error: %s", e)
            self.events.put_nowait(("error", e))
        finally:
            self.events.put_nowait(("closed",))

    async def add_context(self, scene_note: str, greeting_text: str) -> None:
        from google.genai import types

        await self.session.send_client_content(
            turns=[
                types.Content(role="user", parts=[types.Part(text=scene_note)]),
                types.Content(role="model", parts=[types.Part(text=greeting_text)]),
            ],
            turn_complete=False,
        )

    async def send_audio(self, pcm16k: bytes) -> None:
        from google.genai import types

        await self.session.send_realtime_input(
            audio=types.Blob(data=pcm16k, mime_type="audio/pcm;rate=16000")
        )

    async def end_input(self) -> None:
        try:
            await self.session.send_realtime_input(audio_stream_end=True)
        except Exception as e:  # noqa: BLE001
            log.debug("audio_stream_end failed: %s", e)

    async def say(self, instruction: str) -> None:
        from google.genai import types

        await self.session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=instruction)])],
            turn_complete=True,
        )

    async def close(self) -> None:
        if self._rx:
            self._rx.cancel()
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                log.debug("close error: %s", e)
        self._cm = None


def echo_tone(seconds: float = 0.8, rate: int = 16_000) -> bytes:
    """A short warbling tone, standing in for speech when there's no API key."""
    t = np.arange(int(seconds * rate)) / rate
    f = 180 + 30 * np.sin(2 * np.pi * 5 * t)
    tone = 0.3 * np.sin(2 * np.pi * np.cumsum(f) / rate) * np.minimum(1, (seconds - t) * 5)
    return (tone * 32767).astype("<i2").tobytes()


class EchoBrain:
    """No-API test brain: detects when you stop talking and parrots you back
    (through the same FX chain). Good for testing audio plumbing, latency, and
    the mouth envelope without spending anything."""

    out_rate = 16_000
    THRESH = 0.02
    END_SILENCE_S = 0.7

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.events: asyncio.Queue = asyncio.Queue()
        self._buf: list[bytes] = []
        self._speaking = False
        self._silence = 0.0

    async def start(self, system_instruction: str) -> None:
        await asyncio.sleep(0.2)
        log.info("Echo brain ready (no API calls)")

    async def add_context(self, scene_note: str, greeting_text: str) -> None:
        log.info("context: %s", scene_note)

    async def send_audio(self, pcm16k: bytes) -> None:
        x = np.frombuffer(pcm16k, dtype="<i2").astype(np.float32) / 32768.0
        if not x.size:
            return
        rms = float(np.sqrt(np.mean(x * x)))
        dur = x.size / 16_000
        if rms > self.THRESH:
            if not self._speaking:
                self.events.put_nowait(("user_text", "(speech)"))
            self._speaking = True
            self._silence = 0.0
            self._buf.append(pcm16k)
        elif self._speaking:
            self._buf.append(pcm16k)
            self._silence += dur
            if self._silence >= self.END_SILENCE_S:
                self._speaking = False
                data = b"".join(self._buf)
                self._buf = []
                self._emit(data, "(echo of your voice)")

    def _emit(self, pcm: bytes, text: str) -> None:
        step = 3200  # 100 ms at 16 kHz
        for i in range(0, len(pcm), step):
            self.events.put_nowait(("audio", pcm[i : i + step]))
        self.events.put_nowait(("model_text", text))
        self.events.put_nowait(("turn_complete",))

    async def end_input(self) -> None:
        self._buf, self._speaking, self._silence = [], False, 0.0

    async def say(self, instruction: str) -> None:
        self._emit(echo_tone(), f"(tone for: {instruction[:40]}...)")

    async def close(self) -> None:
        pass


def make_brain(cfg: Config):
    if cfg.use_gemini:
        return GeminiBrain(cfg)
    if cfg.brain == "gemini" and not cfg.has_key:
        log.warning("No GEMINI_API_KEY set: using echo brain")
    return EchoBrain(cfg)
