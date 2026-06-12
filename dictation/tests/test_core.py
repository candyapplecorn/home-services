from pathlib import Path
import json
import os
import time

import pytest
import yaml

from dictation_router.config.settings import RoutingMode, load_config
from dictation_router import alerts
from dictation_router.alerts import publish_unrecoverable_recording_alert
from dictation_router.jobs import JobStore
from dictation_router.routing.destination import (
    DestinationSnapshot,
    InsertabilityResult,
    inspect_insertability,
)
from dictation_router.routing.cleaner import clean_transcript
from dictation_router.routing.router import RouteResult, Router
from dictation_router.transcription.postprocess import (
    apply_spoken_punctuation,
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


def test_strip_edge_hallucinations_removes_trailing_thank():
    cleaned, removed = strip_edge_hallucinations(
        "Let's improve the menu a little bit. Thank",
        ["you", "thank", "[BLANK_AUDIO]", "BLANK_AUDIO"],
    )

    assert cleaned == "Let's improve the menu a little bit."
    assert removed == ["Thank"]


def test_strip_edge_hallucinations_removes_blank_audio_marker():
    cleaned, removed = strip_edge_hallucinations(
        "This one should end cleanly. [BLANK_AUDIO]",
        ["you", "thank", "[BLANK_AUDIO]", "BLANK_AUDIO"],
    )

    assert cleaned == "This one should end cleanly."
    assert removed == ["[BLANK_AUDIO]"]


def test_strip_edge_hallucinations_removes_multiline_thank_and_blank_audio():
    cleaned, removed = strip_edge_hallucinations(
        "Let's improve the menu a little bit.\nThank\n[BLANK_AUDIO]",
        ["you", "thank", "[BLANK_AUDIO]", "BLANK_AUDIO"],
    )

    assert cleaned == "Let's improve the menu a little bit."
    assert removed == ["[BLANK_AUDIO]", "Thank"]


def test_job_store_includes_recording_without_audio_for_recovery(tmp_path: Path):
    store = JobStore(jobs_dir=tmp_path)
    job = store.create(RoutingMode.INSERT)

    assert [recoverable.job_id for recoverable in store.recoverable_jobs()] == [job.job_id]
    assert job.status == "starting"


def test_unrecoverable_recording_alert_is_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = JobStore(jobs_dir=tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    monkeypatch.setattr(alerts, "ALERTS_DIR", tmp_path / "alerts")

    alert_path = publish_unrecoverable_recording_alert(
        job,
        reason="recording_stop_timeout_before_audio_saved",
        details="Recorder stop timed out before audio.wav could be written.",
    )

    assert alert_path is not None
    payload = json.loads(alert_path.read_text(encoding="utf-8"))
    assert payload["type"] == "unrecoverable_recording_loss"
    assert payload["job_id"] == job.job_id
    assert "No audio file was written" in payload["message"]


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


def test_apply_spoken_punctuation_basic_marks():
    cleaned, commands = apply_spoken_punctuation("hello comma world period")

    assert cleaned == "hello, world."
    assert commands == ["comma", "period"]


def test_apply_spoken_punctuation_brackets_and_math_symbols():
    cleaned, commands = apply_spoken_punctuation(
        "open parenthesis alpha plus beta close parenthesis multiply gamma equals delta"
    )

    assert cleaned == "(alpha + beta) * gamma = delta"
    assert commands == [
        "open parenthesis",
        "plus",
        "close parenthesis",
        "multiply",
        "equals",
    ]


def test_apply_spoken_punctuation_quotes_and_ellipsis():
    cleaned, commands = apply_spoken_punctuation("open quote hello ellipsis end quote")

    assert cleaned == '"hello..."'
    assert commands == ["open quote", "ellipsis", "end quote"]


def test_apply_spoken_punctuation_accepts_ellipsis_variants():
    cleaned, commands = apply_spoken_punctuation(
        "I have a fix ellipses but also an endpoint ellipse."
    )

    assert cleaned == "I have a fix... but also an endpoint..."
    assert commands == ["ellipses", "ellipse"]


def test_apply_spoken_punctuation_protects_literal_ellipses():
    cleaned, commands = apply_spoken_punctuation("write literal ellipses here")

    assert cleaned == "write ellipses here"
    assert commands == []


def test_apply_spoken_punctuation_collapses_duplicate_commas_from_asr_punctuation():
    cleaned, commands = apply_spoken_punctuation("Basically, comma, I found a problem comma, okay")

    assert cleaned == "Basically, I found a problem, okay"
    assert commands == ["comma", "comma"]


def test_apply_spoken_punctuation_newlines_and_etc():
    cleaned, commands = apply_spoken_punctuation(
        "first line new line second line new paragraph et cetera"
    )

    assert cleaned == "first line\nsecond line\n\netc."
    assert commands == ["new line", "new paragraph", "et cetera"]


def test_apply_spoken_punctuation_protects_literal_words():
    cleaned, commands = apply_spoken_punctuation(
        "write the word comma and literal period not punctuation"
    )

    assert cleaned == "write comma and period not punctuation"
    assert commands == []


def test_apply_spoken_punctuation_accepts_config_overrides():
    cleaned, commands = apply_spoken_punctuation(
        "hello comma world stop",
        {"comma": None, "stop": "."},
    )

    assert cleaned == "hello comma world."
    assert commands == ["stop"]


def test_load_config(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "transcription": {
                    "model": "small.en",
                    "spoken_punctuation": False,
                    "spoken_punctuation_replacements": {"stop": "."},
                },
                "hotkeys": {"insert": "hyper+d"},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.transcription.model == "small.en"
    assert config.transcription.spoken_punctuation is False
    assert config.transcription.spoken_punctuation_replacements == {"stop": "."}
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


class FallbackInserter(FakeInserter):
    def __init__(self, result: InsertabilityResult):
        super().__init__()
        self.result = result

    def can_insert(self, stop_destination=None, require_same_destination=False):  # noqa: ANN001, ARG002
        return self.result


def test_router_insert_mode_falls_back_to_review_when_not_insertable():
    inserter = FallbackInserter(InsertabilityResult(False, "not_insertable:AXButton"))
    editor = FakeEditor()
    router = Router(
        inserter=inserter,
        editor=editor,
        fallback_to_review_when_not_insertable=True,
    )

    result = router.route("hello world", RoutingMode.INSERT)

    assert inserter.last_text is None
    assert editor.last_text == "hello world"
    assert result.actual_mode == RoutingMode.REVIEW
    assert result.fallback_reason == "not_insertable:AXButton"


def test_router_clean_mode_falls_back_to_review_with_cleaned_text():
    inserter = FallbackInserter(InsertabilityResult(False, "focus_changed"))
    editor = FakeEditor()
    router = Router(
        inserter=inserter,
        editor=editor,
        fallback_to_review_when_not_insertable=True,
        fallback_to_review_on_focus_change=True,
    )

    result = router.route("hello hello world", RoutingMode.CLEAN)

    assert inserter.last_text is None
    assert editor.last_text is not None
    assert "hello hello" not in editor.last_text
    assert result.actual_mode == RoutingMode.REVIEW
    assert result.fallback_reason == "focus_changed"


def test_router_focus_change_fallback_can_be_enabled_without_not_insertable_fallback():
    inserter = FallbackInserter(InsertabilityResult(False, "focus_changed"))
    editor = FakeEditor()
    router = Router(
        inserter=inserter,
        editor=editor,
        fallback_to_review_when_not_insertable=False,
        fallback_to_review_on_focus_change=True,
    )

    result = router.route("hello world", RoutingMode.INSERT)

    assert inserter.last_text is None
    assert editor.last_text == "hello world"
    assert result.actual_mode == RoutingMode.REVIEW
    assert result.fallback_reason == "focus_changed"


def test_router_not_insertable_fallback_can_be_disabled_independently():
    inserter = FallbackInserter(InsertabilityResult(False, "not_insertable:AXButton"))
    editor = FakeEditor()
    router = Router(
        inserter=inserter,
        editor=editor,
        fallback_to_review_when_not_insertable=False,
        fallback_to_review_on_focus_change=True,
    )

    result = router.route("hello world", RoutingMode.INSERT)

    assert inserter.last_text == "hello world"
    assert not hasattr(editor, "last_text")
    assert result.actual_mode == RoutingMode.INSERT


def test_insertability_allows_insert_when_destination_probe_is_unknown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("dictation_router.routing.destination.capture_destination_snapshot", lambda: None)

    result = inspect_insertability(require_same_destination=True)

    assert result.insertable is True
    assert result.reason == "destination_unknown_allowed"


def test_insertability_falls_back_when_confident_focus_changed(monkeypatch: pytest.MonkeyPatch):
    stopped = DestinationSnapshot(
        app_name="iTerm2",
        bundle_id="com.googlecode.iterm2",
        pid="123",
        window_title="zsh",
        focused_role="AXTextArea",
        focused_subrole="",
        focused_description="",
        captured_at="2026-06-12T00:00:00+00:00",
    )
    current = DestinationSnapshot(
        app_name="Slack",
        bundle_id="com.tinyspeck.slackmacgap",
        pid="456",
        window_title="Slack",
        focused_role="AXTextArea",
        focused_subrole="",
        focused_description="",
        captured_at="2026-06-12T00:00:01+00:00",
    )
    monkeypatch.setattr(
        "dictation_router.routing.destination.capture_destination_snapshot",
        lambda: current,
    )

    result = inspect_insertability(stop_destination=stopped, require_same_destination=True)

    assert result.insertable is False
    assert result.reason == "focus_changed"


def test_insertability_allows_insert_when_focused_role_is_unknown(monkeypatch: pytest.MonkeyPatch):
    stopped = DestinationSnapshot(
        app_name="iTerm2",
        bundle_id="com.googlecode.iterm2",
        pid="123",
        window_title="zsh",
        focused_role="AXTextArea",
        focused_subrole="",
        focused_description="",
        captured_at="2026-06-12T00:00:00+00:00",
    )
    current = DestinationSnapshot(
        app_name="iTerm2",
        bundle_id="com.googlecode.iterm2",
        pid="123",
        window_title="zsh",
        focused_role="",
        focused_subrole="",
        focused_description="",
        captured_at="2026-06-12T00:00:01+00:00",
    )
    monkeypatch.setattr(
        "dictation_router.routing.destination.capture_destination_snapshot",
        lambda: current,
    )

    result = inspect_insertability(stop_destination=stopped, require_same_destination=True)

    assert result.insertable is True
    assert result.reason == "focused_role_unknown_allowed"


def test_stop_recording_accepts_any_hotkey(tmp_path: Path):
    from unittest.mock import MagicMock, patch

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    app = DictationApp(AppConfig(), MagicMock())
    app.recorder = MagicMock()
    app.recorder.is_recording = False
    app.recorder.raw_path = None
    app.job_store = JobStore(tmp_path / "jobs")
    app.feedback = MagicMock()

    app._on_hotkey(RoutingMode.INSERT)
    assert app._active_mode == RoutingMode.INSERT
    app.recorder.start.assert_called_once()
    started_job = app.job_store.load(app._active_job.job_dir)
    assert started_job.status == "recording"
    assert started_job.data["recording_raw_path"] == str(started_job.audio_path.with_suffix(".raw"))

    app.recorder.is_recording = True
    finished_modes: list[RoutingMode | None] = []

    def capture_finish(mode: RoutingMode | None, destination_snapshot=None) -> None:  # noqa: ANN001
        finished_modes.append(mode)

    def capture_destination(result_queue) -> None:  # noqa: ANN001
        result_queue.put_nowait(None)

    with (
        patch.object(app, "_capture_destination_snapshot", side_effect=capture_destination),
        patch.object(app, "_finish_recording", side_effect=capture_finish),
    ):
        app._on_hotkey(RoutingMode.REVIEW)

    deadline = time.monotonic() + 1
    while not finished_modes and time.monotonic() < deadline:
        time.sleep(0.01)

    assert finished_modes == [RoutingMode.INSERT]
    assert app._processing is True


def test_stop_recording_does_not_wait_for_destination_snapshot():
    from threading import Event
    from unittest.mock import MagicMock, patch

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    app = DictationApp(AppConfig(), MagicMock())
    app.recorder = MagicMock()
    app.recorder.is_recording = True
    app._active_mode = RoutingMode.INSERT
    app._active_job = MagicMock()

    finish_called = Event()

    def slow_capture(result_queue) -> None:  # noqa: ANN001
        time.sleep(0.2)
        result_queue.put_nowait(None)

    def capture_finish(_mode, _destination_snapshot=None) -> None:  # noqa: ANN001
        finish_called.set()

    with (
        patch.object(app, "_capture_destination_snapshot", side_effect=slow_capture),
        patch.object(app, "_finish_recording", side_effect=capture_finish),
    ):
        started = time.monotonic()
        app._on_hotkey(RoutingMode.REVIEW)
        elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert finish_called.wait(0.1)


def test_hotkey_ack_happens_before_recorder_start():
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    events: list[str] = []
    app = DictationApp(AppConfig(), MagicMock())
    app.recorder = MagicMock()
    app.recorder.is_recording = False
    app.recorder.start.side_effect = lambda _audio_path: events.append("recorder_start")
    app.job_store = MagicMock()
    app.job_store.create.return_value = MagicMock()
    app.feedback = MagicMock()
    app.feedback.ack.side_effect = lambda: events.append("ack")
    app._write_activity_state = MagicMock()
    app._log_recording_start_timing = MagicMock()

    app._on_hotkey(RoutingMode.INSERT)

    assert events == ["ack", "recorder_start"]


def test_ignored_hotkey_does_not_ack():
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    app = DictationApp(AppConfig(), MagicMock())
    app.recorder = MagicMock()
    app.recorder.is_recording = False
    app.feedback = MagicMock()
    app._processing = True
    app._processing_started_at = time.monotonic()

    app._on_hotkey(RoutingMode.INSERT)

    app.feedback.ack.assert_not_called()


def test_slow_start_json_includes_timing_spans():
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig

    logger = MagicMock()
    app = DictationApp(AppConfig(), logger)
    app._active_job = MagicMock()

    app._log_recording_start_timing(
        mode=RoutingMode.INSERT,
        hotkey_received=0.0,
        lock_acquired=0.1,
        job_create_started=0.1,
        job_create_done=0.3,
        starting_state_written=0.35,
        ack_requested=0.36,
        recorder_start_started=0.36,
        stream_active=1.7,
        recording_state_written=1.72,
        recording_beep_requested=1.73,
    )

    assert logger.warning.call_args[0][0] == "slow_start_json=%s"
    payload = json.loads(logger.warning.call_args[0][1])
    assert payload["event"] == "recording_start_slow"
    assert payload["job_create_ms"] == 200.0
    assert payload["recorder_start_ms"] == 1340.0
    app._active_job.update.assert_called_once()


def test_stale_processing_state_resets_on_next_hotkey(tmp_path: Path):
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    config = AppConfig()
    config.transcription.processing_timeout_seconds = 1
    app = DictationApp(config, MagicMock())
    recorder = MagicMock()
    recorder.is_recording = False
    recorder.raw_path = None
    app.recorder = recorder
    app._new_recorder = MagicMock(return_value=recorder)
    app.job_store = JobStore(tmp_path / "jobs")
    app.feedback = MagicMock()
    app._processing = True
    app._processing_started_at = time.monotonic() - 2

    app._on_hotkey(RoutingMode.INSERT)

    assert app._processing is False
    assert app._active_mode == RoutingMode.INSERT
    recorder.start.assert_called_once()
    started_job = app.job_store.load(app._active_job.job_dir)
    assert started_job.status == "recording"


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
    old_recorder.recoverable_output_path = None
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


def test_stop_timeout_uses_recoverable_audio_file(tmp_path: Path):
    from unittest.mock import MagicMock, patch

    import numpy as np
    import soundfile as sf

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    config = AppConfig()
    config.transcription.recording_stop_timeout_seconds = 0.01
    app = DictationApp(config, MagicMock())

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    sf.write(str(job.audio_path), np.zeros((1600, 1), dtype="float32"), 16000)

    def hang_stop():
        time.sleep(1)

    recorder = MagicMock()
    recorder.stop.side_effect = hang_stop
    recorder.recoverable_output_path = job.audio_path
    app.recorder = recorder
    app._active_job = job

    with patch("dictation_router.app.os._exit") as exit_mock:
        recovered_path = app._stop_recorder_with_timeout()

    assert recovered_path == job.audio_path
    assert job.data["stop_timeout_recovered_audio"] is True
    exit_mock.assert_not_called()


def test_finish_recording_does_not_cleanup_job_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from unittest.mock import MagicMock

    import numpy as np
    import soundfile as sf

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    sf.write(str(job.audio_path), np.zeros((1600, 1), dtype="float32"), 16000)

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app._active_job = job
    app.feedback = MagicMock()
    app._stop_recorder_with_timeout = MagicMock(return_value=job.audio_path)
    app._process_job = MagicMock(return_value=True)
    monkeypatch.setattr(app, "_cleanup_old_recordings", lambda: None)

    app._finish_recording(RoutingMode.INSERT, destination_snapshot=None)

    assert job.audio_path.is_file()
    app._process_job.assert_called_once()


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


def test_audio_recorder_streams_raw_audio_before_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import numpy as np
    import soundfile as sf

    from dictation_router.audio.recorder import AudioRecorder

    streams = []

    class FakeInputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            streams.append(self)

        def start(self):
            pass

        def abort(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("dictation_router.audio.recorder.sd.InputStream", FakeInputStream)

    output_path = tmp_path / "audio.wav"
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    recorder.start(output_path)
    streams[0].callback(np.ones((1600, 1), dtype="float32"), 1600, None, None)

    raw_path = tmp_path / "audio.raw"
    assert raw_path.is_file()
    assert raw_path.stat().st_size > 0

    assert recorder.stop() == output_path
    assert output_path.is_file()
    assert sf.info(str(output_path)).duration == pytest.approx(0.1)


def test_finalize_raw_recording_to_wav(tmp_path: Path):
    import numpy as np
    import soundfile as sf

    from dictation_router.audio.recorder import finalize_raw_recording_to_wav

    raw_path = tmp_path / "audio.raw"
    output_path = tmp_path / "audio.wav"
    np.ones((1600, 1), dtype="float32").tofile(raw_path)

    assert finalize_raw_recording_to_wav(raw_path, output_path, 16000, 1) == output_path
    assert sf.info(str(output_path)).duration == pytest.approx(0.1)


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
    app.router.route.return_value = RouteResult(RoutingMode.INSERT, RoutingMode.INSERT)
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
    app.router.route.assert_called_once_with(
        "hello after retry",
        RoutingMode.INSERT,
        destination_snapshot=None,
    )
    app.feedback.transcription_failed.assert_called_once()
    app.feedback.transcription_retrying.assert_called_once()


def test_recovered_insert_job_routes_to_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    app = DictationApp(AppConfig(), MagicMock())
    app.feedback = MagicMock()
    app.router = MagicMock()
    app.router.route.return_value = RouteResult(RoutingMode.REVIEW, RoutingMode.REVIEW)
    app.transcriber = MagicMock()
    output_prefix = job.partial_transcript_path.with_suffix("")
    transcript_path = Path(f"{output_prefix}.txt")
    transcript_path.write_text("recovered text", encoding="utf-8")
    app.transcriber.transcribe_detailed.return_value = TranscriptionRunResult(
        text="recovered text",
        command=["whisper-cli"],
        model="medium.en",
        model_path=tmp_path / "ggml-medium.en.bin",
        output_prefix=output_prefix,
        transcript_path=transcript_path,
        started_at="2026-06-12T00:00:00+00:00",
        ended_at="2026-06-12T00:00:01+00:00",
        elapsed_seconds=1.0,
        exit_code=0,
        stdout="",
        stderr="",
    )

    assert app._process_job(job, recovered=True) is True

    app.router.route.assert_called_once_with(
        "recovered text",
        RoutingMode.REVIEW,
        destination_snapshot=None,
    )
    assert job.data["recovered_route_original_mode"] == "insert"
    assert job.data["recovered_route_actual_mode"] == "review"


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


def test_recover_unfinished_jobs_converts_streamed_raw_recording(tmp_path: Path):
    from unittest.mock import MagicMock

    import numpy as np

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    raw_path = job.job_dir / "audio.raw"
    np.ones((1600, 1), dtype="float32").tofile(raw_path)
    job.update(
        audio_file_path=str(job.audio_path),
        recording_raw_path=str(raw_path),
        audio_sample_rate=16000,
        audio_channels=1,
        audio_dtype="float32",
        audio_write_strategy="streamed_raw_pcm",
    )

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.feedback = MagicMock()
    app._process_job = MagicMock(return_value=True)

    app._recover_unfinished_jobs()

    assert job.audio_path.is_file()
    app.feedback.job_recovered.assert_called_once()
    app._process_job.assert_called_once()
    recovered_job = store.load(job.job_dir)
    assert recovered_job.data["recovered_from_streamed_raw_path"] == str(raw_path)


def test_recover_unfinished_starting_job_converts_streamed_raw_recording(tmp_path: Path):
    from unittest.mock import MagicMock

    import numpy as np

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    raw_path = job.job_dir / "audio.raw"
    np.ones((1600, 1), dtype="float32").tofile(raw_path)
    job.update(
        status="starting",
        audio_file_path=str(job.audio_path),
        recording_raw_path=str(raw_path),
        audio_sample_rate=16000,
        audio_channels=1,
    )

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.feedback = MagicMock()
    app._process_job = MagicMock(return_value=True)

    app._recover_unfinished_jobs()

    assert job.audio_path.is_file()
    app.feedback.job_recovered.assert_called_once()
    app._process_job.assert_called_once()


def test_recover_unfinished_job_reports_empty_raw_recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.INSERT)
    raw_path = job.job_dir / "audio.raw"
    raw_path.write_bytes(b"")
    job.update(
        status="starting",
        audio_file_path=str(job.audio_path),
        recording_raw_path=str(raw_path),
        audio_sample_rate=16000,
        audio_channels=1,
        alert_on_unrecoverable=True,
    )
    published: dict[str, str] = {}

    def fake_alert(_job, *, reason, details, logger=None):  # noqa: ANN001, ARG001
        published["reason"] = reason
        published["details"] = details

    monkeypatch.setattr("dictation_router.app.publish_unrecoverable_recording_alert", fake_alert)

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.feedback = MagicMock()
    app._process_job = MagicMock(return_value=True)

    app._recover_unfinished_jobs()

    recovered_job = store.load(job.job_dir)
    assert recovered_job.status == "failed_terminal"
    assert recovered_job.data["raw_recording_recovery_failure"] == "empty"
    assert recovered_job.data["last_error"] == "App exited before recording captured any audio frames"
    assert published["reason"] == "recording_missing_audio_after_restart"
    assert "Raw audio bytes: 0" in published["details"]
    app._process_job.assert_not_called()


def test_recovery_defers_when_dictation_busy(tmp_path: Path):
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.REVIEW)
    audio_path = job.job_dir / "audio.wav"
    audio_path.write_bytes(b"audio")
    job.update(status="recorded", audio_file_path=str(audio_path))

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.recorder = MagicMock()
    app.recorder.is_recording = True
    app._process_job = MagicMock(return_value=True)

    app._recover_unfinished_jobs()

    app._process_job.assert_not_called()


def test_hotkey_is_ignored_while_recovery_is_processing(tmp_path: Path):
    import threading
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.REVIEW)
    audio_path = job.job_dir / "audio.wav"
    audio_path.write_bytes(b"audio")
    job.update(status="recorded", audio_file_path=str(audio_path))

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.feedback = MagicMock()
    app.recorder = MagicMock()
    app.recorder.is_recording = False
    app._write_activity_state = MagicMock()
    recovery_started = threading.Event()
    release_recovery = threading.Event()

    def process_job(_job, recovered=False) -> bool:  # noqa: ANN001, ARG001
        recovery_started.set()
        release_recovery.wait(timeout=1)
        return True

    app._process_job = MagicMock(side_effect=process_job)

    recovery_thread = threading.Thread(target=app._recover_unfinished_jobs)
    recovery_thread.start()
    assert recovery_started.wait(timeout=1)

    app._on_hotkey(RoutingMode.INSERT)

    app.feedback.ack.assert_not_called()
    app.recorder.start.assert_not_called()
    release_recovery.set()
    recovery_thread.join(timeout=1)
    assert not recovery_thread.is_alive()


def test_recovery_does_not_overwrite_recording_state(tmp_path: Path):
    from unittest.mock import MagicMock

    from dictation_router.app import DictationApp
    from dictation_router.config.settings import AppConfig
    from dictation_router.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    job = store.create(RoutingMode.REVIEW)
    audio_path = job.job_dir / "audio.wav"
    audio_path.write_bytes(b"audio")
    job.update(status="recorded", audio_file_path=str(audio_path))

    app = DictationApp(AppConfig(), MagicMock())
    app.job_store = store
    app.recorder = MagicMock()
    app.recorder.is_recording = False
    app._write_activity_state = MagicMock()

    def process_job(_job, recovered=False) -> bool:  # noqa: ANN001, ARG001
        app.recorder.is_recording = True
        return True

    app._process_job = MagicMock(side_effect=process_job)

    app._recover_unfinished_jobs()

    assert app._write_activity_state.call_args_list[-1].args == ("recording",)


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
