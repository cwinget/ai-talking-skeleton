"""settings_store: override round-trip and validation. Run: python -m tests.test_settings_store"""
from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("GEMINI_API_KEY", "")

from skeleton.config import load_config  # noqa: E402
from skeleton.settings_store import (  # noqa: E402
    ValidationError,
    clear_overrides,
    effective,
    load_overrides,
    save_overrides,
)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    cfg = replace(load_config(), settings_file=tmp / "settings.json")

    # untouched: effective() is just cfg
    assert load_overrides(cfg) == {}
    assert effective(cfg).voice == cfg.voice

    # save + round trip
    save_overrides(cfg, {"voice": "Puck", "fx_pitch": -6})
    assert load_overrides(cfg) == {"voice": "Puck", "fx_pitch": -6.0}
    eff = effective(cfg)
    assert eff.voice == "Puck" and eff.fx_pitch == -6.0
    assert eff.character_name == cfg.character_name  # untouched fields fall through

    # merge: a second save keeps earlier keys
    save_overrides(cfg, {"max_turns": 3})
    merged = load_overrides(cfg)
    assert merged["voice"] == "Puck" and merged["max_turns"] == 3

    # validation: out-of-range and unknown keys are rejected, nothing is written
    before = load_overrides(cfg)
    try:
        save_overrides(cfg, {"fx_pitch": 99})
        assert False, "expected ValidationError"
    except ValidationError:
        pass
    try:
        save_overrides(cfg, {"not_a_real_field": 1})
        assert False, "expected ValidationError"
    except ValidationError:
        pass
    assert load_overrides(cfg) == before

    # reset
    clear_overrides(cfg)
    assert load_overrides(cfg) == {}
    assert effective(cfg).voice == cfg.voice

    # a corrupt file is ignored, not fatal
    cfg.settings_file.write_text("not json")
    assert load_overrides(cfg) == {}

    print("SETTINGS STORE TESTS PASSED")


if __name__ == "__main__":
    main()
