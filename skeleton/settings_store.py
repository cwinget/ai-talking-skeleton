"""Admin-UI-editable settings, layered over the .env-loaded Config the same
way mode.txt layers over PERSONA_MODE: a small JSON file that beats the
default, takes effect for the *next* conversation, and can be cleared to
fall back to .env.

    overrides = load_overrides(cfg)        # {} if untouched
    cfg = effective(cfg)                   # Config with overrides applied
    save_overrides(cfg, {"voice": "Puck"})  # validated, merged, persisted
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .config import Config

log = logging.getLogger("skeleton.settings")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    type: str  # "float" | "int" | "str" | "opt_float"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    hidden: bool = False  # kept in the store but edited by a dedicated UI card, not the generic form


SCHEMA: list[Field] = [
    Field("character_name", "Character name", "Voice & Persona", "str"),
    Field("voice", "Voice", "Voice & Persona", "str"),
    Field("candy_rule", "Candy rule", "Voice & Persona", "str"),
    Field("fx_pitch", "Pitch (semitones)", "Voice & Persona", "float", -12, 12, 0.5),
    Field("fx_drive_db", "Drive (dB)", "Voice & Persona", "float", 0, 24, 1),
    Field("fx_reverb", "Reverb (wet)", "Voice & Persona", "float", 0, 1, 0.05),
    Field("fx_gain_db", "Gain (dB)", "Voice & Persona", "float", -24, 24, 1),
    Field("scary_voice", "Scary voice (blank = same)", "Scary overrides", "str"),
    Field("scary_fx_pitch", "Scary pitch (semitones)", "Scary overrides", "opt_float", -12, 12, 0.5),
    Field("scary_fx_reverb", "Scary reverb (wet)", "Scary overrides", "opt_float", 0, 1, 0.05),
    Field("scary_fx_drive_db", "Scary drive (dB)", "Scary overrides", "opt_float", 0, 24, 1),
    Field("silence_timeout_s", "Silence timeout (s)", "Timing", "float", 2, 30, 1),
    Field("max_turns", "Max turns", "Timing", "int", 1, 20, 1),
    Field("max_conversation_s", "Max conversation (s)", "Timing", "float", 15, 300, 5),
    Field("cooldown_s", "Cooldown (s)", "Timing", "float", 0, 120, 1),
    Field("vad_silence_ms", "VAD silence (ms)", "Timing", "int", 200, 2000, 50),
    Field("ambient_file", "Background audio file", "Background audio", "str", hidden=True),
    Field("ambient_volume", "Background audio volume", "Background audio", "float", 0, 1, 0.01, hidden=True),
]
_BY_KEY = {f.key: f for f in SCHEMA}


class ValidationError(ValueError):
    pass


def _coerce(field: Field, value: Any) -> Any:
    if field.type == "str":
        if not isinstance(value, str):
            raise ValidationError(f"{field.key}: expected a string")
        return value
    if value is None and field.type == "opt_float":
        return None
    try:
        num = float(value) if field.type in ("float", "opt_float") else int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field.key}: expected a number") from None
    if field.min is not None and num < field.min:
        raise ValidationError(f"{field.key}: must be >= {field.min}")
    if field.max is not None and num > field.max:
        raise ValidationError(f"{field.key}: must be <= {field.max}")
    return num


def load_overrides(cfg: Config) -> dict[str, Any]:
    try:
        raw = json.loads(cfg.settings_file.read_text())
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        log.warning("ignoring unreadable %s: %s", cfg.settings_file.name, e)
        return {}
    out = {}
    for key, value in raw.items():
        field = _BY_KEY.get(key)
        if field is None:
            continue
        try:
            out[key] = _coerce(field, value)
        except ValidationError as e:
            log.warning("ignoring stored override: %s", e)
    return out


def effective(cfg: Config) -> Config:
    overrides = load_overrides(cfg)
    return replace(cfg, **overrides) if overrides else cfg


def save_overrides(cfg: Config, patch: dict[str, Any]) -> dict[str, Any]:
    unknown = set(patch) - set(_BY_KEY)
    if unknown:
        raise ValidationError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    coerced = {key: _coerce(_BY_KEY[key], value) for key, value in patch.items()}
    merged = {**load_overrides(cfg), **coerced}
    tmp = cfg.settings_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2))
    os.replace(tmp, cfg.settings_file)
    return merged


def clear_overrides(cfg: Config) -> None:
    cfg.settings_file.unlink(missing_ok=True)


def schema_json() -> list[dict[str, Any]]:
    return [
        {"key": f.key, "label": f.label, "group": f.group, "type": f.type,
         "min": f.min, "max": f.max, "step": f.step}
        for f in SCHEMA if not f.hidden
    ]


def values_json(cfg: Config) -> dict[str, Any]:
    eff = effective(cfg)
    return {f.key: getattr(eff, f.key) for f in SCHEMA}
