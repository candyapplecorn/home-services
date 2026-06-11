from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MODEL_DIR = (
    Path.home()
    / "Library/Application Support/HomeServices/ai-helper/models/gemma-4-e4b-it"
)


@dataclass(frozen=True)
class Settings:
    model: str = str(DEFAULT_MODEL_DIR)
    host: str = "127.0.0.1"
    port: int = 8765
    max_new_tokens: int = 512
    enable_thinking: bool = False
    whisper_model: str = "medium.en"
    whisper_cli: str = "whisper-cli"
    whisper_models_dir: str = "~/.cache/whisper-cpp"


def _read_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings(
        model=os.environ.get("AI_HELPER_MODEL", Settings.model),
        host=os.environ.get("AI_HELPER_HOST", Settings.host),
        port=_read_int("AI_HELPER_PORT", Settings.port),
        max_new_tokens=_read_int(
            "AI_HELPER_MAX_NEW_TOKENS", Settings.max_new_tokens
        ),
        enable_thinking=_read_bool("AI_HELPER_ENABLE_THINKING", False),
        whisper_model=os.environ.get("AI_HELPER_WHISPER_MODEL", Settings.whisper_model),
        whisper_cli=os.environ.get("AI_HELPER_WHISPER_CLI", Settings.whisper_cli),
        whisper_models_dir=os.environ.get(
            "AI_HELPER_WHISPER_MODELS_DIR", Settings.whisper_models_dir
        ),
    )
