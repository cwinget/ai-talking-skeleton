"""Which persona is active right now, and the per-mode config (voice, FX,
greetings folder)."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, time

from .config import Config
from .prompts import MODES

log = logging.getLogger("skeleton.modes")
VALID = ("auto", "family", "scary")


def _hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def now_for(cfg: Config) -> datetime:
    """The real time, or PRETEND_TIME / --pretend-time (today at HH:MM) for testing."""
    if cfg.pretend_time:
        return datetime.combine(datetime.now().date(), _hhmm(cfg.pretend_time))
    return datetime.now()


def in_scary_window(cfg: Config, now: datetime | None = None) -> bool:
    t = (now or now_for(cfg)).time()
    start, end = _hhmm(cfg.scary_start), _hhmm(cfg.scary_end)
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # window wraps past midnight


def requested_mode(cfg: Config) -> str:
    """mode.txt (if present and valid) beats PERSONA_MODE from .env."""
    try:
        v = cfg.mode_file.read_text().strip().lower()
        if v in VALID:
            return v
        if v:
            log.warning("ignoring %s: %r is not one of %s", cfg.mode_file.name, v, VALID)
    except FileNotFoundError:
        pass
    return cfg.persona_mode if cfg.persona_mode in VALID else "auto"


def current_mode(cfg: Config, now: datetime | None = None) -> str:
    m = requested_mode(cfg)
    if m == "auto":
        return "scary" if in_scary_window(cfg, now) else "family"
    return m


def cfg_for_mode(cfg: Config, mode: str) -> Config:
    """Config with this mode's voice/FX overrides and its own greetings folder."""
    assert mode in MODES
    changes = {"greetings_dir": cfg.greetings_dir / mode}
    if mode == "scary":
        if cfg.scary_voice:
            changes["voice"] = cfg.scary_voice
        if cfg.scary_fx_pitch is not None:
            changes["fx_pitch"] = cfg.scary_fx_pitch
        if cfg.scary_fx_reverb is not None:
            changes["fx_reverb"] = cfg.scary_fx_reverb
        if cfg.scary_fx_drive_db is not None:
            changes["fx_drive_db"] = cfg.scary_fx_drive_db
    return replace(cfg, **changes)
