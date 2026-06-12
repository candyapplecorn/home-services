from pathlib import Path
import os
import time

import pytest
import yaml

from dictation_router.config.settings import RoutingMode, load_config
from dictation_router.routing.cleaner import clean_transcript
from dictation_router.routing.router import Router
from dictation_router.transcription.postprocess import (
    normalize_transcript_newlines,
    strip_edge_hallucinations,
)
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


def test_normalize_transcript_newlines_joins_accidental_prose_breaks():
    raw = (
        "a really stupid AI would\n"
        "\u00a0be able to do that but unfortunately it takes RAM. "
        "The only problem then is if my\n"
        "\u00a0is it would be like having a remote connection."
    )

    assert normalize_transcript_newlines(raw) == (
        "a really stupid AI would be able to do that but unfortunately it takes RAM. "
        "The only problem then is if my is it would be like having a remote connection."
    )


def test_normalize_transcript_newlines_preserves_blank_line_paragraphs():
    raw = "First paragraph wraps\ninside one thought.\n\nSecond paragraph stays separate."

    assert normalize_transcript_newlines(raw) == (
        "First paragraph wraps inside one thought.\n\nSecond paragraph stays separate."
    )


def test_normalize_transcript_newlines_preserves_list_blocks():
    raw = "- first item\n- second item\n- third item"

    assert normalize_transcript_newlines(raw) == raw


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


def test_finish_recording_restarts_process_when_recorder_stop_hangs():
    from unittest.mock import MagicMock, patch

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    config = AppConfig()
    config.transcription.recording_stop_timeout_seconds = 0.01
    app = DictationApp(config, MagicMock())

    old_recorder = MagicMock()

    def hang_stop():
        time.sleep(1)

    old_recorder.stop.side_effect = hang_stop
    app.recorder = old_recorder
    app.feedback = MagicMock()
    app._processing = True
    app._processing_started_at = time.monotonic()

    with patch("dictation_router.app.os._exit") as exit_mock:
        app._finish_recording(RoutingMode.INSERT)

    assert app._processing is False
    assert app._processing_started_at is None
    exit_mock.assert_called_once_with(75)
    app.feedback.error.assert_called_once()


def test_job_store_persists_and_recovers_recorded_job(tmp_path: Path):
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.REVIEW)
    audio_source = tmp_path / "source.wav"
    audio_source.write_bytes(b"fake audio")

    job.attach_audio(audio_source)
    job.update(status="failed_retryable", last_error="temporary failure")

    assert job.job_json_path.is_file()
    assert job.status_path.read_text(encoding="utf-8") == "failed_retryable\n"
    assert job.audio_path.read_bytes() == b"fake audio"
    assert [recovered.job_id for recovered in store.recoverable_jobs()] == [job.job_id]


def test_whisper_transcriber_captures_stdout_stderr_and_command(tmp_path: Path):
    from subprocess import CompletedProcess
    from unittest.mock import patch

    from dictation_router.transcription.whisper_cpp import WhisperCppTranscriber

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "ggml-small.en.bin").write_bytes(b"model")
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    output_prefix = tmp_path / "job" / "transcript.partial"
    output_prefix.parent.mkdir()

    def fake_run(cmd, capture_output, text, check):  # noqa: ARG001
        transcript_path = Path(f"{cmd[cmd.index('-of') + 1]}.txt")
        transcript_path.write_text("hello world", encoding="utf-8")
        return CompletedProcess(cmd, 0, stdout="stdout details", stderr="stderr details")

    transcriber = WhisperCppTranscriber(
        model="small.en",
        whisper_cli="whisper-cli",
        models_dir=models_dir,
        threads=3,
        processors=1,
        metal=False,
    )

    with patch("dictation_router.transcription.whisper_cpp.subprocess.run", side_effect=fake_run):
        result = transcriber.transcribe_detailed(
            audio_path,
            output_prefix=output_prefix,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
        )

    assert result.text == "hello world"
    assert result.exit_code == 0
    assert "-t" in result.command
    assert "3" in result.command
    assert "-ng" in result.command
    assert (tmp_path / "stdout.log").read_text(encoding="utf-8") == "stdout details"
    assert (tmp_path / "stderr.log").read_text(encoding="utf-8") == "stderr details"


def test_process_job_retries_failed_transcription_and_preserves_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import MagicMock

    import numpy as np
    import soundfile as sf

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import DictationJob, JobStore
    from dictation_router.transcription.whisper_cpp import TranscriptionRunResult

    monkeypatch.setattr(DictationJob, "record_memory_pressure", lambda self: None)

    audio_source = tmp_path / "source.wav"
    sf.write(str(audio_source), np.zeros((1600, 1), dtype="float32"), 16000)

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    job.attach_audio(audio_source)

    config = AppConfig()
    config.transcription.retry_count = 1
    config.transcription.retry_with_smaller_model = False
    app = DictationApp(config, MagicMock())
    app.job_store = store
    app.router = MagicMock()
    app.feedback = MagicMock()

    def successful_result(*args, **kwargs):  # noqa: ANN002, ANN003
        output_prefix = kwargs["output_prefix"]
        transcript_path = Path(f"{output_prefix}.txt")
        transcript_path.write_text("hello after retry", encoding="utf-8")
        return TranscriptionRunResult(
            text="hello after retry",
            command=["whisper-cli", "-f", str(job.audio_path)],
            model="medium.en",
            model_path=tmp_path / "ggml-medium.en.bin",
            output_prefix=output_prefix,
            transcript_path=transcript_path,
            started_at="2026-06-12T00:00:00+00:00",
            ended_at="2026-06-12T00:00:01+00:00",
            elapsed_seconds=1.0,
            exit_code=0,
            stdout="ok",
            stderr="",
        )

    calls = {"count": 0}

    def transcribe_side_effect(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary whisper failure")
        return successful_result(*args, **kwargs)

    app.transcriber = MagicMock()
    app.transcriber.transcribe_detailed.side_effect = transcribe_side_effect

    assert app._process_job(job) is True

    assert job.status == "completed"
    assert job.data["failure_count"] == 1
    assert job.audio_path.is_file()
    assert job.final_transcript_path.read_text(encoding="utf-8") == "hello after retry"
    assert app.transcriber.transcribe_detailed.call_count == 2
    app.router.route.assert_called_once_with("hello after retry", RoutingMode.INSERT)
    app.feedback.transcription_failed.assert_called_once()
    app.feedback.transcription_retrying.assert_called_once()


def test_recover_unfinished_jobs_processes_recorded_jobs(tmp_path: Path):
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.CLEAN)
    audio_path = job.job_dir / "audio.wav"
    audio_path.write_bytes(b"audio")
    job.update(status="recorded", audio_file_path=str(audio_path))

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.feedback = MagicMock()
    app._process_job = MagicMock(return_value=True)

    app._recover_unfinished_jobs()

    app.feedback.job_recovered.assert_called_once()
    app._process_job.assert_called_once()


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
