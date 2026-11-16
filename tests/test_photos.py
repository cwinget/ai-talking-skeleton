"""Camera frames are only written to disk when PHOTOS_KEEP > 0. Run: python -m tests.test_photos"""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from skeleton.config import load_config
from skeleton.server import Hub


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "photos"
        cfg = replace(load_config(), photos_dir=d, photos_keep=0)
        fake = SimpleNamespace(cfg=cfg)
        assert Hub._save_photo(fake, b"\xff\xd8jpeg") is None
        assert not d.exists(), "PHOTOS_KEEP=0 must not write anything"

        fake.cfg = replace(cfg, photos_keep=2)
        for _ in range(4):
            assert Hub._save_photo(fake, b"\xff\xd8jpeg")
        assert len(list(d.glob("*.jpg"))) == 2, "only the newest PHOTOS_KEEP frames are kept"
    print("PHOTOS TEST PASSED")


if __name__ == "__main__":
    main()
