"""Persona-mode selection and legacy greeting migration. Run: python -m tests.test_modes"""
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

os.environ.setdefault("GEMINI_API_KEY", "")

from skeleton.config import load_config  # noqa: E402
from skeleton.greetings import _migrate_legacy, load_greetings  # noqa: E402
from skeleton.modes import cfg_for_mode, current_mode  # noqa: E402
from skeleton.prompts import MODES, persona_prompt  # noqa: E402


def at(h, m):
    return datetime(2026, 10, 31, h, m)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    cfg = replace(load_config(), persona_mode="auto", scary_start="20:30", scary_end="05:00",
                  mode_file=tmp / "mode.txt", greetings_dir=tmp / "greetings")
    # time window (wraps midnight)
    assert current_mode(cfg, at(19, 0)) == "family"
    assert current_mode(cfg, at(20, 30)) == "scary"
    assert current_mode(cfg, at(1, 0)) == "scary"
    assert current_mode(cfg, at(5, 0)) == "family"
    # fixed modes
    assert current_mode(replace(cfg, persona_mode="scary"), at(12, 0)) == "scary"
    assert current_mode(replace(cfg, persona_mode="family"), at(22, 0)) == "family"
    # mode.txt overrides .env; junk is ignored
    (tmp / "mode.txt").write_text("family\n")
    assert current_mode(cfg, at(22, 0)) == "family"
    (tmp / "mode.txt").write_text("scary")
    assert current_mode(replace(cfg, persona_mode="family"), at(12, 0)) == "scary"
    (tmp / "mode.txt").write_text("banana")
    assert current_mode(cfg, at(12, 0)) == "family"
    # per-mode overrides only touch scary
    c = replace(cfg, scary_voice="Algenib", scary_fx_pitch=-7.0)
    assert cfg_for_mode(c, "family").voice == cfg.voice
    assert cfg_for_mode(c, "scary").voice == "Algenib"
    assert cfg_for_mode(c, "scary").fx_pitch == -7.0
    # prompts contain the shared safety rules
    for mode in MODES:
        p = persona_prompt(cfg, mode)
        assert "Hard rules" in p and "COSTUMES only" in p
    assert "Fear check" in persona_prompt(cfg, "scary")
    # pretend time drives auto mode when no explicit time is passed
    assert current_mode(replace(cfg, mode_file=tmp / "none.txt", pretend_time="21:15")) == "scary"
    assert current_mode(replace(cfg, mode_file=tmp / "none.txt", pretend_time="12:00")) == "family"
    # legacy greetings (flat folder) move into family/
    g = cfg.greetings_dir
    g.mkdir(parents=True)
    (g / "greet_01.wav").write_bytes(b"")
    (g / "greetings.json").write_text(json.dumps([]))
    _migrate_legacy(cfg)
    assert (g / "family" / "greet_01.wav").exists() and not (g / "greet_01.wav").exists()
    assert load_greetings(cfg_for_mode(cfg, "scary"))  # placeholder when none generated
    print("MODE TESTS PASSED")


if __name__ == "__main__":
    main()
