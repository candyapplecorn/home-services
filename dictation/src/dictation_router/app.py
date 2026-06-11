from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import soundfile as sf

from dictation_router.audio.recorder import AudioRecorder
from dictation_router.config.settings import AppConfig, RoutingMode, ensure_app_dirs
from dictation_router.routing.editor import EditorLauncher
from dictation_router.routing.inserter import TextInserter
from dictation_router.routing.router import Router
from dictation_router.transcription.whisper_cpp import WhisperCppTranscriber
from dictation_router.ui.feedback import AudioFeedback
from dictation_router.ui.hotkeys import HotkeyManager
from dictation_router.ui.permissions import check_accessibility, describe_hotkey


class DictationApp:
    """Orchestrate hotkeys, recording, transcription, and routing."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.feedback = AudioFeedback()
        self.recorder = AudioRecorder(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )
        self.transcriber = WhisperCppTranscriber(
            model=config.transcription.model,
            whisper_cli=config.transcription.whisper_cli,
            models_dir=config.transcription.whisper_models_dir,
            split_on_word=config.transcription.split_on_word,
            no_speech_threshold=config.transcription.no_speech_threshold,
            logprob_threshold=config.transcription.logprob_threshold,
        )
        self.router = Router(
            inserter=TextInserter(max_typing_chars=config.routing.max_typing_chars),
            editor=EditorLauncher(preferred_editors=config.editor.preferred),
            logger=logger,
        )
        self._lock = threading.Lock()
        self._active_mode: RoutingMode | None = None
        self._processing = False
        self._keep_recordings = config.transcription.keep_recordings
        self._min_chars_per_minute = config.transcription.min_chars_per_minute
        self._hotkeys = HotkeyManager(
            {
                config.hotkeys.insert: lambda: self._on_hotkey(RoutingMode.INSERT),
                config.hotkeys.review: lambda: self._on_hotkey(RoutingMode.REVIEW),
                config.hotkeys.clean: lambda: self._on_hotkey(RoutingMode.CLEAN),
            }
        )

    def _on_hotkey(self, mode: RoutingMode) -> None:
        with self._lock:
            if self._processing:
                self.logger.info("Ignoring hotkey while processing")
                return

            if not self.recorder.is_recording:
                self._active_mode = mode
                self.logger.info("Recording started (%s mode)", mode.value)
                try:
                    self.recorder.start()
                    self.feedback.recording_started()
                except Exception as exc:
                    self.logger.exception("Failed to start recording: %s", exc)
                    self.feedback.error()
                    self._active_mode = None
                return

            active_mode = self._active_mode
            if active_mode != mode:
                self.logger.info(
                    "Stopping recording (%s mode) via %s hotkey",
                    active_mode.value if active_mode else "unknown",
                    mode.value,
                )
            self._processing = True

        threading.Thread(
            target=self._finish_recording,
            args=(active_mode,),
            daemon=True,
        ).start()

    def _finish_recording(self, mode: RoutingMode | None) -> None:
        try:
            self.logger.info("Recording stopped (%s mode)", mode.value if mode else "unknown")
            self.feedback.recording_stopped()

            audio_path = self.recorder.stop()
            duration_s = sf.info(str(audio_path)).duration
            self.logger.info(
                "Saved recording to %s (%.1fs, %.1f KB)",
                audio_path,
                duration_s,
                audio_path.stat().st_size / 1024,
            )

            started = time.perf_counter()
            transcript = self.transcriber.transcribe(audio_path)
            elapsed = time.perf_counter() - started
            self.logger.info(
                "Transcription completed in %.2fs (%d chars, %.0f chars/min of audio)",
                elapsed,
                len(transcript),
                (len(transcript) / duration_s * 60) if duration_s > 0 else 0,
            )
            if duration_s >= 30:
                chars_per_min = len(transcript) / duration_s * 60
                if chars_per_min < self._min_chars_per_minute:
                    self.logger.warning(
                        "Low transcript density (%.0f chars/min, expected ~400+ for continuous speech). "
                        "Whisper may have skipped quiet/pause segments. "
                        "Try review mode, speak closer to mic, or lower transcription.no_speech_threshold.",
                        chars_per_min,
                    )

            if mode is not None:
                self.router.route(transcript, mode)

            self.feedback.transcription_complete()
        except Exception as exc:
            self.logger.exception("Processing failed: %s", exc)
            self.feedback.error()
        finally:
            with self._lock:
                self._active_mode = None
                self._processing = False
            self._cleanup_recording(audio_path if "audio_path" in locals() else None)

    def _cleanup_recording(self, audio_path: Path | None) -> None:
        if self._keep_recordings or not audio_path or not audio_path.is_file():
            return
        audio_path.unlink(missing_ok=True)

    def run(self) -> None:
        ensure_app_dirs()
        self.logger.info("Dictation Router started")
        self.logger.info(
            "Insert: %s  (%s)",
            self.config.hotkeys.insert,
            describe_hotkey(self.config.hotkeys.insert),
        )
        self.logger.info(
            "Review: %s  (%s)",
            self.config.hotkeys.review,
            describe_hotkey(self.config.hotkeys.review),
        )
        self.logger.info(
            "Clean: %s  (%s)",
            self.config.hotkeys.clean,
            describe_hotkey(self.config.hotkeys.clean),
        )
        self.logger.info("Whisper model: %s", self.config.transcription.model)

        if not check_accessibility(self.logger):
            self.logger.error("Waiting for Accessibility permission — hotkeys disabled until restart.")

        self._hotkeys.start()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            self.logger.info("Shutting down")
        finally:
            self._hotkeys.stop()
