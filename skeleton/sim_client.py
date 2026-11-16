"""Simulated skeleton device for the Mac. Speaks the exact same protocol the
ESP32 firmware will, using the Mac's mic, speakers, and webcam.

    python -m skeleton.sim_client                 # Mac is the whole skeleton (role "both")
    python -m skeleton.sim_client --role body     # Mac = radar (Enter key) + webcam + mouth meter;
                                                  #   pair with the ReSpeaker as the audio device
    python -m skeleton.sim_client --role audio    # Mac = mic + speaker only
    python -m skeleton.sim_client --list-devices  # show audio devices

Controls (type + Enter):
    <Enter>  visitor arrives (radar trigger)
    l        visitor leaves
    q        quit
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import threading
import time

import sounddevice as sd
from dotenv import load_dotenv
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from . import protocol as P

# Same .env as the server, so DEVICE_TOKEN set there is picked up as the --token default.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


class Speaker:
    """Jitter buffer + output stream. Tracks when a play_id has fully drained."""

    def __init__(self, device, mouth: bool):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.mouth = mouth
        self.env_q: list[int] = []
        self.current_env = 0
        self.stream = sd.RawOutputStream(
            samplerate=P.DEVICE_RATE, channels=1, dtype="int16",
            blocksize=P.FRAME_SAMPLES, device=device, callback=self._cb,
        )

    def _cb(self, outdata, frames, time_info, status):
        need = frames * 2
        with self.lock:
            chunk = bytes(self.buf[:need])
            del self.buf[:need]
            env = self.env_q.pop(0) if self.env_q else 0
        if len(chunk) < need:
            chunk += b"\x00" * (need - len(chunk))
        outdata[:] = chunk
        self.current_env = env

    def push(self, env: int, pcm: bytes) -> None:
        with self.lock:
            self.buf.extend(pcm)
            self.env_q.append(env)

    def clear(self) -> None:
        with self.lock:
            self.buf.clear()
            self.env_q.clear()

    def empty(self) -> bool:
        with self.lock:
            return not self.buf


class Camera:
    def __init__(self, index: int):
        import cv2

        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError("could not open webcam (check System Settings > Privacy > Camera)")
        self.lock = threading.Lock()
        self.latest = None
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()  # keep frames fresh

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.latest = frame
            else:
                time.sleep(0.05)

    def grab_jpeg(self) -> bytes | None:
        with self.lock:
            frame = None if self.latest is None else self.latest.copy()
        if frame is None:
            return None
        h, w = frame.shape[:2]
        if w > 768:
            frame = self.cv2.resize(frame, (768, int(h * 768 / w)))
        ok, enc = self.cv2.imencode(".jpg", frame, [self.cv2.IMWRITE_JPEG_QUALITY, 80])
        return enc.tobytes() if ok else None


class NullStream:
    latency = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class NullSpeaker:
    """Stand-in when this client doesn't do audio (role=body)."""

    def __init__(self):
        self.stream = NullStream()
        self.current_env = 0
        self.lock = threading.Lock()
        self.buf = b""

    def push(self, env, pcm):
        pass

    def clear(self):
        pass

    def empty(self):
        return True


async def run(args) -> None:
    loop = asyncio.get_running_loop()
    does_audio = args.role in ("audio", "both")
    does_body = args.role in ("body", "both")
    speaker = Speaker(args.output_device, args.mouth) if does_audio else NullSpeaker()
    camera = None
    if does_body and not args.no_camera:
        try:
            camera = Camera(args.camera)
            print("camera: on")
        except Exception as e:  # noqa: BLE001
            print(f"camera: off ({e})")

    mic_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)

    def mic_cb(indata, frames, time_info, status):
        data = bytes(indata)
        loop.call_soon_threadsafe(lambda: mic_q.full() or mic_q.put_nowait(data))

    mic = (
        sd.RawInputStream(
            samplerate=P.DEVICE_RATE, channels=1, dtype="int16",
            blocksize=P.FRAME_SAMPLES, device=args.input_device, callback=mic_cb,
        )
        if does_audio
        else NullStream()
    )

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else None
    async with connect(args.url, max_size=8 * 1024 * 1024, additional_headers=headers) as ws:
        print(f"connected to {args.url} (output latency {speaker.stream.latency * 1000:.0f} ms)")
        await ws.send(json.dumps({"type": "hello", "role": args.role, "device": "mac-sim",
                                  "rate": P.DEVICE_RATE}))
        print(f"role: {args.role}")
        pending_done: list[int] = []

        async def send_mic():
            while True:
                await ws.send(await mic_q.get())

        async def capture(count: int, interval_ms: int):
            if camera is None:
                return
            for i in range(count):
                jpg = await loop.run_in_executor(None, camera.grab_jpeg)
                if jpg:
                    await ws.send(json.dumps({"type": "image", "seq": i,
                                              "jpeg_b64": base64.b64encode(jpg).decode()}))
                await asyncio.sleep(interval_ms / 1000)

        async def watch_playback():
            # Report playback_done once the buffer drains + the output latency passes.
            while True:
                await asyncio.sleep(0.02)
                if pending_done and speaker.empty():
                    await asyncio.sleep(speaker.stream.latency)
                    if speaker.empty():
                        pid = pending_done.pop(0)
                        await ws.send(json.dumps({"type": "playback_done", "id": pid}))
                        if args.debug:
                            print(f"[playback_done {pid}]")

        async def mouth_meter():
            if not args.mouth:
                await asyncio.Event().wait()  # never finishes (don't end the client)
            while True:
                await asyncio.sleep(0.05)
                env = speaker.current_env
                if env or not speaker.empty() or not does_audio:
                    bar = "#" * (env * 20 // 255)
                    sys.stdout.write(f"\r  mouth [{bar:<20}] ")
                    sys.stdout.flush()

        async def receive():
            async for msg in ws:
                if isinstance(msg, bytes):
                    if msg and msg[0] == P.MSG_MOUTH:  # separate-body mouth level
                        speaker.current_env = msg[1]
                        continue
                    env, pcm = P.unpack_audio(msg)
                    speaker.push(env, pcm)
                    continue
                m = json.loads(msg)
                t = m.get("type")
                if t == "play_end":
                    pending_done.append(m["id"])
                    if args.debug:
                        with speaker.lock:
                            queued = len(speaker.buf) / (2 * P.DEVICE_RATE)
                        print(f"[play_end {m['id']}: {queued:.2f}s still queued]")
                elif t == "capture":
                    asyncio.create_task(capture(m.get("count", 3), m.get("interval_ms", 500)))
                elif t == "state":
                    if args.mouth:
                        sys.stdout.write("\n")
                    print(f"[state: {m.get('state')}]")
                elif t == "stop":
                    speaker.clear()

        async def keyboard():
            print("\nControls: <Enter> = visitor arrives, l = visitor leaves, q = quit\n")
            while True:
                line = (await loop.run_in_executor(None, sys.stdin.readline)).strip().lower()
                if line == "q":
                    return
                if line == "l":
                    await ws.send(json.dumps({"type": "presence", "present": False}))
                    print("-> visitor left")
                else:
                    await ws.send(json.dumps({"type": "presence", "present": True}))
                    print("-> visitor arrived")

        with mic, speaker.stream:
            tasks = [asyncio.create_task(c) for c in (send_mic(), watch_playback(), receive(), mouth_meter())]
            kb = asyncio.create_task(keyboard())
            done, _ = await asyncio.wait([kb, *tasks], return_when=asyncio.FIRST_COMPLETED)
            for t in tasks + [kb]:
                t.cancel()
            for t in done:
                if t is not kb and not t.cancelled() and t.exception() and not isinstance(t.exception(), ConnectionClosed):
                    raise t.exception()
    if camera:
        camera.running = False


def main() -> None:
    ap = argparse.ArgumentParser(description="Mac simulated skeleton device")
    ap.add_argument("--url", default="ws://localhost:8765")
    ap.add_argument("--token", default=os.environ.get("DEVICE_TOKEN", ""),
                    help="server's DEVICE_TOKEN (default: $DEVICE_TOKEN)")
    ap.add_argument("--role", choices=["both", "body", "audio"], default="both",
                    help="which part of the skeleton this Mac plays (default: both)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--input-device", default=None, help="mic device index or name")
    ap.add_argument("--output-device", default=None, help="speaker device index or name")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--mouth", action="store_true", help="show the mouth/LED level meter")
    ap.add_argument("--debug", action="store_true", help="print playback bookkeeping")
    args = ap.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return
    for name in ("input_device", "output_device"):
        v = getattr(args, name)
        if v is not None and v.isdigit():
            setattr(args, name, int(v))
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"Could not connect: {e}. Is the server running?")


if __name__ == "__main__":
    main()
