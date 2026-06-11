from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

APP_SUPPORT = Path.home() / "Library/Application Support/DictationRouter"
TRANSCRIPTS_DIR = APP_SUPPORT / "transcripts"
LOGS_DIR = APP_SUPPORT / "logs"
RECORDINGS_DIR = APP_SUPPORT / "recordings"


class RoutingMode(str, Enum):
    INSERT = "insert"
    REVIEW = "review"
    CLEAN = "clean"


@dataclass
class TranscriptionConfig:
    model: str = "medium.en"
    whisper_cli: str = "whisper-cli"
    whisper_models_dir: Path = field(default_factory=lambda: Path("~/.cache/whisper-cpp").expanduser())
    keep_recordings: bool = False
    recording_retention_hours: float = 24.0
    split_on_word: bool = True
    no_speech_threshold: float = 0.35
    logprob_threshold: float = -1.0
    min_chars_per_minute: float = 200.0
    edge_hallucinations: list[str] = field(default_factory=lambda: ["you"])
    processing_timeout_seconds: float = 30.0
    recording_stop_timeout_seconds: float = 15.0


@dataclass
class RoutingConfig:
    max_typing_chars: int = 500


@dataclass
class EditorConfig:
    preferred: list[str] = field(default_factory=lambda: ["WebStorm", "Rider", "TextEdit"])


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    device: int | str | None = None


@dataclass
class HotkeyConfig:
    insert: str = "hyper+d"
    review: str = "hyper+r"
    clean: str = "hyper+c"


@dataclass
class AppConfig:
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expanduser(str(value)))


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or Path("config.yaml")
    if not config_path.is_file():
        return AppConfig()

    with config_path.open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}

    transcription_raw = raw.get("transcription", {})
    routing_raw = raw.get("routing", {})
    editor_raw = raw.get("editor", {})
    hotkeys_raw = raw.get("hotkeys", {})
    audio_raw = raw.get("audio", {})

    return AppConfig(
        transcription=TranscriptionConfig(
            model=transcription_raw.get("model", "medium.en"),
            whisper_cli=transcription_raw.get("whisper_cli", "whisper-cli"),
            whisper_models_dir=_expand_path(
                transcription_raw.get("whisper_models_dir", "~/.cache/whisper-cpp")
            ),
            keep_recordings=bool(transcription_raw.get("keep_recordings", False)),
            recording_retention_hours=float(transcription_raw.get("recording_retention_hours", 24.0)),
            split_on_word=bool(transcription_raw.get("split_on_word", True)),
            no_speech_threshold=float(transcription_raw.get("no_speech_threshold", 0.35)),
            logprob_threshold=float(transcription_raw.get("logprob_threshold", -1.0)),
            min_chars_per_minute=float(transcription_raw.get("min_chars_per_minute", 200.0)),
            edge_hallucinations=list(transcription_raw.get("edge_hallucinations", ["you"])),
            processing_timeout_seconds=float(transcription_raw.get("processing_timeout_seconds", 30.0)),
            recording_stop_timeout_seconds=float(
                transcription_raw.get("recording_stop_timeout_seconds", 15.0)
            ),
        ),
        routing=RoutingConfig(
            max_typing_chars=int(routing_raw.get("max_typing_chars", 500)),
        ),
        editor=EditorConfig(
            preferred=list(editor_raw.get("preferred", ["WebStorm", "Rider", "TextEdit"])),
        ),
        hotkeys=HotkeyConfig(
            insert=hotkeys_raw.get("insert", "hyper+d"),
            review=hotkeys_raw.get("review", "hyper+r"),
            clean=hotkeys_raw.get("clean", "hyper+c"),
        ),
        audio=AudioConfig(
            sample_rate=int(audio_raw.get("sample_rate", 16000)),
            channels=int(audio_raw.get("channels", 1)),
            device=audio_raw.get("device"),
        ),
    )


def ensure_app_dirs() -> None:
    for directory in (APP_SUPPORT, TRANSCRIPTS_DIR, LOGS_DIR, RECORDINGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
