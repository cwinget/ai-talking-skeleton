"""Regression tests for the pitch shifter / FX chain. Run: python -m tests.test_fx"""
import os

os.environ.setdefault("GEMINI_API_KEY", "")

import numpy as np  # noqa: E402

from skeleton.config import load_config  # noqa: E402
from skeleton.fx import LowLatencyPitch, VoiceFX  # noqa: E402


def main() -> None:
    rng = np.random.default_rng(0)
    # Tiny and empty chunks at phase 0 (the Halloween-night crash).
    for n in (0, 1, 2, 3):
        LowLatencyPitch(-4, 24000).process(np.zeros(n, np.float32))
    # Random chunk sizes, many phases, several shift amounts; output length must equal input.
    for semis in (-7, -4, -1, 3):
        ps = LowLatencyPitch(semis, 24000)
        total_in = total_out = 0
        for _ in range(3000):
            n = int(rng.integers(0, 400))
            y = ps.process(rng.standard_normal(n).astype(np.float32) * 0.1)
            total_in += n
            total_out += y.size
            assert np.isfinite(y).all()
        assert total_in == total_out
    # Odd-length PCM chunks through the whole chain.
    fx = VoiceFX(load_config(), 24000)
    pcm = (rng.standard_normal(24000) * 3000).astype("<i2").tobytes()
    i = 0
    while i < len(pcm):
        n = int(rng.integers(1, 999))
        fx.process_pcm16(pcm[i : i + n])
        i += n
    fx.flush()
    print("FX TESTS PASSED")


if __name__ == "__main__":
    main()
