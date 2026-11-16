"""Configuration loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _num(name: str, default):
    """A blank value (e.g. `PHOTOS_KEEP=` in .env) means "use the default"."""
    v = os.getenv(name, "").strip()
    return v if v else str(default)


def _float(name: str, default: float) -> float:
    return float(_num(name, default))


def _int(name: str, default: int) -> int:
    return int(_num(name, default))


def _opt_float(name: str) -> float | None:
    v = os.getenv(name, "").strip()
    return float(v) if v else None


def _bool(name: str, default: bool) -> bool:
    return _num(name, default).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    api_key: str
    live_model: str
    vision_model: str
    brain: str
    voice: str
    character_name: str
    candy_rule: str

    fx_enabled: bool
    fx_pitch: float
    fx_drive_db: float
    fx_reverb: float
    fx_gain_db: float
    fx_tail_s: float

    max_conversation_s: float
    max_turns: int
    silence_timeout_s: float
    cooldown_s: float
    vad_silence_ms: int
    connect_timeout_s: float
    turn_stall_s: float
    echo_guard_s: float
    mouth_delay_s: float

    vision_enabled: bool
    vision_frames: int
    vision_interval_ms: int
    vision_grace_s: float
    vision_delay_s: float

    persona_mode: str          # "auto" | "family" | "scary"
    scary_start: str           # "HH:MM" local time; auto mode switches to scary at this time
    scary_end: str             # "HH:MM"; and back to family at this time (may wrap past midnight)
    mode_file: Path            # optional runtime override: contains family / scary / auto
    pretend_time: str          # "HH:MM" = pretend it's this time (testing auto mode); "" = real clock
    scary_voice: str           # "" = same as VOICE
    scary_fx_pitch: float | None
    scary_fx_reverb: float | None
    scary_fx_drive_db: float | None

    chatter_interval_s: float  # random-phrases mode: gap between phrases
    camera_rotate_180: bool    # body camera is mounted upside down: rotate frames 180 degrees on arrival
    device_token: str          # shared secret devices send as 'Authorization: Bearer ...'; "" = no auth
    host: str
    port: int
    admin_port: int
    log_level: str
    greetings_dir: Path
    photos_dir: Path
    photos_keep: int           # 0 = never write camera frames to disk (default)
    settings_file: Path       # admin UI overrides (voice/FX/timing); beats .env, like mode_file
    ambient_dir: Path         # background-audio mp3s offered in the admin UI
    ambient_file: str         # which one plays (admin UI can override)
    ambient_volume: float     # 0..1 (admin UI can override); music only, the voice is unaffected

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def use_gemini(self) -> bool:
        return self.brain == "gemini" and self.has_key


def load_config() -> Config:
    return Config(
        api_key=_str("GEMINI_API_KEY", "") or _str("GOOGLE_API_KEY", ""),
        live_model=_str("LIVE_MODEL", "gemini-3.8-live"),
        vision_model=_str("VISION_MODEL", "gemini-3.8-flash"),
        brain=_str("BRAIN", "gemini").lower(),
        voice=_str("VOICE", "Charon"),
        character_name=_str("CHARACTER_NAME", "Old Bones"),
        candy_rule=_str(
            "CANDY_RULE",
            "If it comes up naturally, remind them to take ONE piece of candy from the bowl.",
        ),
        fx_enabled=_bool("FX_ENABLED", True),
        fx_pitch=_float("FX_PITCH_SEMITONES", -4.0),
        fx_drive_db=_float("FX_DRIVE_DB", 0.0),
        fx_reverb=_float("FX_REVERB", 0.3),
        fx_gain_db=_float("FX_GAIN_DB", 0.0),
        fx_tail_s=_float("FX_TAIL_S", 0.4),
        max_conversation_s=_float("MAX_CONVERSATION_S", 90),
        max_turns=_int("MAX_TURNS", 6),
        silence_timeout_s=_float("SILENCE_TIMEOUT_S", 8),
        cooldown_s=_float("COOLDOWN_S", 10),
        vad_silence_ms=_int("VAD_SILENCE_MS", 700),
        connect_timeout_s=_float("CONNECT_TIMEOUT_S", 6),
        turn_stall_s=_float("TURN_STALL_S", 8),
        echo_guard_s=_float("ECHO_GUARD_S", 0.15),
        mouth_delay_s=_float("MOUTH_DELAY_MS", 120) / 1000.0,
        vision_enabled=_bool("VISION_ENABLED", False),
        vision_frames=_int("VISION_FRAMES", 3),
        vision_interval_ms=_int("VISION_INTERVAL_MS", 500),
        vision_grace_s=_float("VISION_GRACE_S", 1.0),
        vision_delay_s=_float("VISION_DELAY_S", 1.5),
        persona_mode=_str("PERSONA_MODE", "auto").lower(),
        scary_start=_str("SCARY_START", "20:30"),
        scary_end=_str("SCARY_END", "05:00"),
        mode_file=Path(_str("MODE_FILE", str(PROJECT_ROOT / "mode.txt"))),
        pretend_time=_str("PRETEND_TIME", ""),
        scary_voice=_str("SCARY_VOICE", ""),
        scary_fx_pitch=_opt_float("SCARY_FX_PITCH_SEMITONES"),
        scary_fx_reverb=_opt_float("SCARY_FX_REVERB"),
        scary_fx_drive_db=_opt_float("SCARY_FX_DRIVE_DB"),
        chatter_interval_s=_float("CHATTER_INTERVAL_S", 30),
        camera_rotate_180=_bool("CAMERA_ROTATE_180", False),
        device_token=_str("DEVICE_TOKEN", ""),
        host=_str("HOST", "0.0.0.0"),
        port=_int("PORT", 8765),
        admin_port=_int("ADMIN_PORT", 8080),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
        photos_dir=Path(_str("PHOTOS_DIR", str(PROJECT_ROOT / "photos"))),
        photos_keep=_int("PHOTOS_KEEP", 0),
        greetings_dir=Path(_str("GREETINGS_DIR", str(PROJECT_ROOT / "greetings"))),
        settings_file=Path(_str("SETTINGS_FILE", str(PROJECT_ROOT / "settings.json"))),
        ambient_dir=Path(_str("AMBIENT_DIR", str(PROJECT_ROOT / "ambient"))),
        ambient_file=_str("AMBIENT_FILE", "haunted.mp3"),
        ambient_volume=_float("AMBIENT_VOLUME", 0.5),
    )
