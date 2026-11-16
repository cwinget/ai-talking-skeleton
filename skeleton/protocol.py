"""Device <-> server wire protocol. See PROTOCOL.md for the full spec.

Binary frames
  device -> server : raw mic PCM, s16le mono @ 16 kHz (any length; 20 ms = 640 bytes recommended)
  server -> device : [0x01][env u8][PCM s16le mono @ 16 kHz, 20 ms = 640 bytes]
                     env = mouth/LED level 0..255 for exactly this chunk of audio

Text frames: JSON objects with a "type" field (see PROTOCOL.md).
"""
from __future__ import annotations

DEVICE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = DEVICE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2  # 640

MSG_AUDIO = 0x01
MSG_MOUTH = 0x02  # server -> body: [0x02][env u8]


def pack_audio(env: int, pcm: bytes) -> bytes:
    return bytes((MSG_AUDIO, max(0, min(255, env)))) + pcm


def pack_mouth(env: int) -> bytes:
    return bytes((MSG_MOUTH, max(0, min(255, env))))


def unpack_audio(data: bytes) -> tuple[int, bytes]:
    if len(data) < 2 or data[0] != MSG_AUDIO:
        raise ValueError("not an audio frame")
    return data[1], data[2:]
