from pathlib import Path
import os
import time

import pytest
import yaml

from dictation_router.config.settings import RoutingMode, load_config
from dictation_router.routing.cleaner import clean_transcript
from dictation_router.routing.router import Router
from dictation_router.transcription.postprocess import strip_edge_hallucinations
from dictation_router.ui.hotkeys import parse_hotkey


def test_parse_hyper_hotkey():
    assert parse_hotkey("hyper+d") == "<ctrl>+<alt>+<shift>+<cmd>+d"


def test_parse_cmd_alt_ctrl_hotkey():
    parsed = parse_hotkey("cmd+alt+ctrl+d")
    assert "<cmd>" in parsed
    assert "<alt>" in parsed
    assert "<ctrl>" in parsed
    assert parsed.endswith("d")


def test_clean_transcript_removes_duplicates_and_capitalizes():
    raw = "hello hello world this is a test"
    cleaned = clean_transcript(raw)
    assert "hello hello" not in cleaned
    assert cleaned[0].isupper()
    assert cleaned.endswith(".")


def test_strip_edge_hallucinations_removes_trailing_glued_you():
    cleaned, removed = strip_edge_hallucinations("I just don't want to eat pieyou", ["you"])
    assert cleaned == "I just don't want to eat pie"
    assert removed == ["you"]


def test_strip_edge_hallucinations_preserves_internal_you():
    cleaned, removed = strip_edge_hallucinations("Can you please stop screaming at meyou", ["you"])
    assert cleaned == "Can you please stop screaming at me"
    assert removed == ["you"]


def test_strip_edge_hallucinations_removes_standalone_edges():
    cleaned, removed = strip_edge_hallucinations("you Okay this time it worked you", ["you"])
    assert cleaned == "Okay this time it worked"
    assert removed == ["you", "you"]


def test_strip_edge_hallucinations_removes_only_you():
    cleaned, removed = strip_edge_hallucinations("you", ["you"])
    assert cleaned == ""
    assert removed == ["you"]


def test_load_config(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "transcription": {"model": "small.en"},
                "hotkeys": {"insert": "hyper+d"},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.transcription.model == "small.en"
    assert config.hotkeys.insert == "hyper+d"


class FakeInserter:
    def __init__(self):
        self.last_text = None

    def insert(self, text: str) -> None:
        self.last_text = text


class FakeEditor:
    def open_transcript(self, text: str):
        self.last_text = text
        return Path("/tmp/test.txt")


def test_router_insert_mode():
    inserter = FakeInserter()
    editor = FakeEditor()
    router = Router(inserter=inserter, editor=editor)
    router.route("hello world", RoutingMode.INSERT)
    assert inserter.last_text == "hello world"


def test_router_clean_mode():
    inserter = FakeInserter()
    editor = FakeEditor()
    router = Router(inserter=inserter, editor=editor)
    router.route("hello hello world", RoutingMode.CLEAN)
    assert inserter.last_text is not None
    assert "hello hello" not in inserter.last_text


def test_stop_recording_accepts_any_hotkey():
    from unittest.mock import MagicMock, patch

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    app = DictationApp(AppConfig(), MagicMock())
    app.recorder = MagicMock()
    app.recorder.is_recording = False
    app.feedback = MagicMock()

    app._on_hotkey(RoutingMode.INSERT)
    assert app._active_mode == RoutingMode.INSERT
    app.recorder.start.assert_called_once()

    app.recorder.is_recording = True
    finished_modes: list[RoutingMode | None] = []

    def capture_finish(mode: RoutingMode | None) -> None:
        finished_modes.append(mode)

    with patch.object(app, "_finish_recording", side_effect=capture_finish):
        app._on_hotkey(RoutingMode.REVIEW)

    assert finished_modes == [RoutingMode.INSERT]
    assert app._processing is True


def test_stale_processing_state_resets_on_next_hotkey():
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    config = AppConfig()
    config.transcription.processing_timeout_seconds = 1
    app = DictationApp(config, MagicMock())
    recorder = MagicMock()
    recorder.is_recording = False
    app.recorder = recorder
    app._new_recorder = MagicMock(return_value=recorder)
    app.feedback = MagicMock()
    app._processing = True
    app._processing_started_at = time.monotonic() - 2

    app._on_hotkey(RoutingMode.INSERT)

    assert app._processing is False
    assert app._active_mode == RoutingMode.INSERT
    recorder.start.assert_called_once()


def test_finish_recording_recovers_when_recorder_stop_hangs():
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    config = AppConfig()
    config.transcription.recording_stop_timeout_seconds = 0.01
    app = DictationApp(config, MagicMock())

    old_recorder = MagicMock()

    def hang_stop():
        time.sleep(1)

    old_recorder.stop.side_effect = hang_stop
    new_recorder = MagicMock()
    app.recorder = old_recorder
    app._new_recorder = MagicMock(return_value=new_recorder)
    app.feedback = MagicMock()
    app._processing = True
    app._processing_started_at = time.monotonic()

    app._finish_recording(RoutingMode.INSERT)

    assert app.recorder is new_recorder
    assert app._processing is False
    assert app._processing_started_at is None
    app.feedback.error.assert_called_once()


def test_cleanup_old_recordings_respects_retention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    old_recording = tmp_path / "old.wav"
    recent_recording = tmp_path / "recent.wav"
    old_note = tmp_path / "old.txt"
    old_recording.write_bytes(b"old")
    recent_recording.write_bytes(b"recent")
    old_note.write_text("leave me", encoding="utf-8")

    old_mtime = time.time() - (25 * 60 * 60)
    os.utime(old_recording, (old_mtime, old_mtime))
    os.utime(old_note, (old_mtime, old_mtime))

    config = AppConfig()
    config.transcription.recording_retention_hours = 24
    app = DictationApp(config, MagicMock())
    monkeypatch.setattr("dictation_router.app.RECORDINGS_DIR", tmp_path)

    app._cleanup_old_recordings()

    assert not old_recording.exists()
    assert recent_recording.exists()
    assert old_note.exists()
