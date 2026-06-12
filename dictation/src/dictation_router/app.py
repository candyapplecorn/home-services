from __future__ import annotations

import logging
import json
import os
import queue
import signal
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from dictation_router.alerts import publish_unrecoverable_recording_alert
from dictation_router.audio.recorder import AudioRecorder, finalize_raw_recording_to_wav
from dictation_router.config.settings import (
    RECORDINGS_DIR,
    STATE_FILE,
    AppConfig,
    RoutingMode,
    ensure_app_dirs,
)
from dictation_router.jobs import DictationJob, JobStore, utc_now_iso
from dictation_router.routing.destination import DestinationSnapshot, capture_destination_snapshot
from dictation_router.routing.editor import EditorLauncher
from dictation_router.routing.inserter import TextInserter
from dictation_router.routing.router import Router
from dictation_router.transcription.postprocess import (
    apply_spoken_punctuation,
    normalize_transcript_newlines,
    strip_edge_hallucinations,
)
from dictation_router.transcription.whisper_cpp import WhisperCppError, WhisperCppTranscriber
from dictation_router.ui.feedback import AudioFeedback
from dictation_router.ui.hotkeys import HotkeyManager
from dictation_router.ui.permissions import check_accessibility, describe_hotkey


class DictationApp:
    """Orchestrate hotkeys, recording, transcription, and routing."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.feedback = AudioFeedback()
        self.recorder = self._new_recorder()
        self.job_store = JobStore()
        self.transcriber = WhisperCppTranscriber(
            model=config.transcription.model,
            whisper_cli=config.transcription.whisper_cli,
            models_dir=config.transcription.whisper_models_dir,
            split_on_word=config.transcription.split_on_word,
            no_speech_threshold=config.transcription.no_speech_threshold,
            logprob_threshold=config.transcription.logprob_threshold,
            threads=config.transcription.threads,
            processors=config.transcription.processors,
            metal=config.transcription.metal,
        )
        self.router = Router(
            inserter=TextInserter(max_typing_chars=config.routing.max_typing_chars),
            editor=EditorLauncher(preferred_editors=config.editor.preferred),
            logger=logger,
            fallback_to_review_when_not_insertable=config.routing.fallback_to_review_when_not_insertable,
            fallback_to_review_on_focus_change=config.routing.fallback_to_review_on_focus_change,
        )
        self._lock = threading.Lock()
        self._transcription_lock = threading.Lock()
        self._active_mode: RoutingMode | None = None
        self._processing = False
        self._processing_started_at: float | None = None
        self._recovering = False
        self._active_job: DictationJob | None = None
        self._keep_recordings = config.transcription.keep_recordings
        self._min_chars_per_minute = config.transcription.min_chars_per_minute
        self._hotkeys = HotkeyManager(
            {
                config.hotkeys.insert: lambda: self._on_hotkey(RoutingMode.INSERT),
                config.hotkeys.review: lambda: self._on_hotkey(RoutingMode.REVIEW),
                config.hotkeys.clean: lambda: self._on_hotkey(RoutingMode.CLEAN),
            }
        )

    def _new_recorder(self) -> AudioRecorder:
        return AudioRecorder(
            sample_rate=self.config.audio.sample_rate,
            channels=self.config.audio.channels,
            device=self.config.audio.device,
        )

    def _on_hotkey(self, mode: RoutingMode) -> None:
        hotkey_received = time.perf_counter()
        active_mode: RoutingMode | None = None
        job: DictationJob | None = None

        with self._lock:
            lock_acquired = time.perf_counter()
            if self._processing:
                if self._recovering:
                    self.logger.info("Ignoring hotkey while recovering unfinished jobs")
                    return

                elapsed = (
                    time.monotonic() - self._processing_started_at
                    if self._processing_started_at is not None
                    else 0
                )
                if elapsed < self.config.transcription.processing_timeout_seconds:
                    self.logger.info("Ignoring hotkey while processing")
                    return

                self.logger.error(
                    "Processing appears stuck after %.1fs; resetting state and starting a new recording",
                    elapsed,
                )
                self._processing = False
                self._processing_started_at = None
                self._active_mode = None
                self.recorder = self._new_recorder()

            if not self.recorder.is_recording:
                self._active_mode = mode
                job_create_started = time.perf_counter()
                self._active_job = self.job_store.create(mode)
                expected_audio_path = self._active_job.audio_path
                expected_raw_path = expected_audio_path.with_suffix(".raw")
                self._active_job.update(
                    status="starting",
                    audio_file_path=str(expected_audio_path),
                    recording_raw_path=str(expected_raw_path),
                    audio_sample_rate=self.config.audio.sample_rate,
                    audio_channels=self.config.audio.channels,
                    audio_dtype="float32",
                    audio_write_strategy="streamed_raw_pcm",
                    recording_start_requested_at=utc_now_iso(),
                    alert_on_unrecoverable=True,
                    unrecoverable_alert_reason="recording_missing_audio_after_restart",
                )
                job_create_done = time.perf_counter()
                try:
                    self._write_activity_state("starting")
                    starting_state_written = time.perf_counter()
                    self.feedback.ack()
                    ack_requested = time.perf_counter()
                    recorder_start_started = time.perf_counter()
                    self.recorder.start(expected_audio_path)
                    stream_active = time.perf_counter()
                    if self._active_job is not None:
                        raw_path = self.recorder.raw_path
                        self._active_job.update(
                            status="recording",
                            recording_raw_path=(
                                str(raw_path) if isinstance(raw_path, Path) else str(expected_raw_path)
                            ),
                            recording_stream_started_at=utc_now_iso(),
                        )
                    self._write_activity_state("recording")
                    recording_state_written = time.perf_counter()
                    self.feedback.recording_started()
                    recording_beep_requested = time.perf_counter()
                    self.logger.info("Recording started (%s mode)", mode.value)
                    self._log_recording_start_timing(
                        mode=mode,
                        hotkey_received=hotkey_received,
                        lock_acquired=lock_acquired,
                        job_create_started=job_create_started,
                        job_create_done=job_create_done,
                        starting_state_written=starting_state_written,
                        ack_requested=ack_requested,
                        recorder_start_started=recorder_start_started,
                        stream_active=stream_active,
                        recording_state_written=recording_state_written,
                        recording_beep_requested=recording_beep_requested,
                    )
                except Exception as exc:
                    self.logger.exception("Failed to start recording: %s", exc)
                    self.feedback.error()
                    self._write_activity_state("idle")
                    if self._active_job is not None:
                        self._active_job.update(
                            status="failed_terminal",
                            last_error=f"Failed to start recording: {exc}",
                            failed_at=utc_now_iso(),
                        )
                    self._active_job = None
                    self._active_mode = None
                return

            active_mode = self._active_mode
            job = self._active_job
            if active_mode != mode:
                self.logger.info(
                    "Stopping recording (%s mode) via %s hotkey",
                    active_mode.value if active_mode else "unknown",
                    mode.value,
                )
            self._processing = True
            self._processing_started_at = time.monotonic()
            self._write_activity_state("processing")

        destination_queue: queue.Queue[DestinationSnapshot | None] = queue.Queue(maxsize=1)
        threading.Thread(
            target=self._capture_destination_snapshot,
            args=(destination_queue,),
            name="dictation-destination-snapshot",
            daemon=True,
        ).start()

        threading.Thread(
            target=self._finish_recording,
            args=(active_mode, destination_queue),
            daemon=True,
        ).start()

    def _capture_destination_snapshot(
        self,
        result_queue: queue.Queue[DestinationSnapshot | None],
    ) -> None:
        try:
            destination_snapshot = capture_destination_snapshot()
            result_queue.put_nowait(destination_snapshot)
        except Exception as exc:
            self.logger.warning("Failed to capture stop destination: %s", exc)
            try:
                result_queue.put_nowait(None)
            except queue.Full:
                pass

    def _resolve_destination_snapshot(
        self,
        destination_source: DestinationSnapshot | queue.Queue[DestinationSnapshot | None] | None,
    ) -> DestinationSnapshot | None:
        if isinstance(destination_source, queue.Queue):
            try:
                return destination_source.get(timeout=0.8)
            except queue.Empty:
                self.logger.warning("Timed out waiting for stop destination snapshot")
                return None
        return destination_source

    def _log_recording_start_timing(
        self,
        mode: RoutingMode,
        hotkey_received: float,
        lock_acquired: float,
        job_create_started: float,
        job_create_done: float,
        starting_state_written: float,
        ack_requested: float,
        recorder_start_started: float,
        stream_active: float,
        recording_state_written: float,
        recording_beep_requested: float,
    ) -> None:
        elapsed_ms = {
            "lock_wait_ms": (lock_acquired - hotkey_received) * 1000,
            "job_create_ms": (job_create_done - job_create_started) * 1000,
            "starting_state_ms": (starting_state_written - job_create_done) * 1000,
            "ack_request_ms": (ack_requested - starting_state_written) * 1000,
            "recorder_start_ms": (stream_active - recorder_start_started) * 1000,
            "recording_state_ms": (recording_state_written - stream_active) * 1000,
            "recording_beep_request_ms": (recording_beep_requested - recording_state_written) * 1000,
            "hotkey_to_stream_active_ms": (stream_active - hotkey_received) * 1000,
            "hotkey_to_recording_beep_ms": (recording_beep_requested - hotkey_received) * 1000,
        }
        if elapsed_ms["hotkey_to_stream_active_ms"] < (
            self.config.hotkeys.slow_start_threshold_seconds * 1000
        ):
            return

        payload = {
            "event": "recording_start_slow",
            "mode": mode.value,
            **{key: round(value, 2) for key, value in elapsed_ms.items()},
        }
        self.logger.warning("slow_start_json=%s", json.dumps(payload, sort_keys=True))
        if self._active_job is not None:
            self._active_job.update(recording_start_slow=payload)

    def _finish_recording(
        self,
        mode: RoutingMode | None,
        destination_snapshot: (
            DestinationSnapshot | queue.Queue[DestinationSnapshot | None] | None
        ) = None,
    ) -> None:
        source_audio_path: Path | None = None
        job_audio_path: Path | None = None
        job = self._active_job
        try:
            self.logger.info("Recording stopped (%s mode)", mode.value if mode else "unknown")
            self.feedback.recording_stopped()

            self.logger.info("Stopping audio stream and writing recording")
            source_audio_path = self._stop_recorder_with_timeout()
            self.logger.info("Audio stream stopped; inspecting recording")
            if job is None:
                job = self.job_store.create(mode)
            job_audio_path = job.attach_audio(source_audio_path)

            duration_s = sf.info(str(job_audio_path)).duration
            audio, _sample_rate = sf.read(str(job_audio_path), dtype="float32", always_2d=True)
            peak_level = float(np.max(np.abs(audio))) if audio.size else 0.0
            rms_level = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
            job.update(
                audio_duration_seconds=duration_s,
                audio_peak_level=peak_level,
                audio_rms_level=rms_level,
                audio_file_size_bytes=job_audio_path.stat().st_size,
            )
            self.logger.info(
                "Saved recording to %s (%.1fs, %.1f KB, peak %.4f, rms %.4f)",
                job_audio_path,
                duration_s,
                job_audio_path.stat().st_size / 1024,
                peak_level,
                rms_level,
            )
            if peak_level < 0.01 or rms_level < 0.001:
                self.logger.warning(
                    "Recording looks nearly silent (peak %.4f, rms %.4f). "
                    "Check the selected microphone and macOS Microphone permission for the terminal/tmux host.",
                    peak_level,
                    rms_level,
                )

            resolved_destination = self._resolve_destination_snapshot(destination_snapshot)
            if resolved_destination is not None:
                job.update(stop_destination=resolved_destination.to_dict())
            with self._transcription_lock:
                self._process_job(job, destination_snapshot=resolved_destination)
        except Exception as exc:
            self.logger.exception("Processing failed: %s", exc)
            if job is not None:
                job.update(
                    status="failed_terminal",
                    last_error=str(exc),
                    failed_at=utc_now_iso(),
                )
            self.feedback.error()
        finally:
            with self._lock:
                self._active_mode = None
                self._processing = False
                self._processing_started_at = None
                self._active_job = None
            self._write_activity_state("idle")
            if source_audio_path != job_audio_path:
                self._cleanup_recording(source_audio_path)
            self._cleanup_old_recordings()

    def _process_job(
        self,
        job: DictationJob,
        recovered: bool = False,
        destination_snapshot: DestinationSnapshot | None = None,
    ) -> bool:
        requested_mode = job.mode
        mode = RoutingMode.REVIEW if recovered and requested_mode is not None else requested_mode
        if destination_snapshot is None:
            raw_destination = job.data.get("stop_destination")
            destination_snapshot = DestinationSnapshot.from_dict(
                raw_destination if isinstance(raw_destination, dict) else None
            )
        if recovered and requested_mode is not None:
            job.update(
                recovered_route_original_mode=requested_mode.value,
                recovered_route_actual_mode=RoutingMode.REVIEW.value,
            )
        audio_path = job.audio_path
        if not audio_path.is_file():
            job.update(
                status="failed_terminal",
                last_error=f"Missing audio file for job: {audio_path}",
                failed_at=utc_now_iso(),
            )
            self.logger.error("Cannot process job %s; missing audio file %s", job.job_id, audio_path)
            self.feedback.error()
            return False

        duration_s = float(job.data.get("audio_duration_seconds") or sf.info(str(audio_path)).duration)
        max_audio_seconds = self.config.transcription.max_audio_minutes * 60
        if max_audio_seconds > 0 and duration_s > max_audio_seconds:
            job.update(
                status="failed_terminal",
                last_error=(
                    f"Audio duration {duration_s:.1f}s exceeds max_audio_minutes "
                    f"{self.config.transcription.max_audio_minutes:.1f}"
                ),
                failed_at=utc_now_iso(),
            )
            self.logger.error("Job %s audio exceeds configured max duration; preserving %s", job.job_id, audio_path)
            self.feedback.error()
            return False

        models = self._attempt_models()
        failure_count = int(job.data.get("failure_count", 0))
        if recovered:
            self.logger.info("Recovering dictation job %s from status=%s", job.job_id, job.status)

        while failure_count < len(models):
            model = models[failure_count]
            attempt_number = failure_count + 1
            job.update(
                status="transcribing",
                attempt_number=attempt_number,
                max_attempts=len(models),
                model=model,
                transcription_started_at=utc_now_iso(),
            )
            job.record_memory_pressure()
            self.feedback.transcription_started()

            try:
                result = self.transcriber.transcribe_detailed(
                    audio_path,
                    output_prefix=job.partial_transcript_path.with_suffix(""),
                    stdout_path=job.stdout_path,
                    stderr_path=job.stderr_path,
                    model=model,
                )
            except Exception as exc:
                failure_count += 1
                retryable = failure_count < len(models)
                failure_metadata = exc.result.to_metadata() if isinstance(exc, WhisperCppError) else {}
                job.update(
                    **failure_metadata,
                    status="failed_retryable" if retryable else "failed_terminal",
                    failure_count=failure_count,
                    retry_count=max(0, failure_count - 1),
                    last_error=str(exc),
                    last_exception_type=type(exc).__name__,
                    stdout_log=str(job.stdout_path),
                    stderr_log=str(job.stderr_path),
                    audio_file_path=str(audio_path),
                    failed_at=utc_now_iso(),
                )
                self.logger.exception(
                    "Transcription job %s failed attempt %d/%d with model %s: %s",
                    job.job_id,
                    attempt_number,
                    len(models),
                    model,
                    exc,
                )
                self.feedback.transcription_failed()
                if retryable:
                    self.logger.info("Retrying dictation job %s", job.job_id)
                    self.feedback.transcription_retrying()
                    continue
                return False

            job.write_text(job.partial_transcript_path, result.text)
            job.update(
                **result.to_metadata(),
                status="transcribed",
                failure_count=failure_count,
                stdout_log=str(job.stdout_path),
                stderr_log=str(job.stderr_path),
                audio_file_path=str(audio_path),
            )

            transcript, removed_hallucinations = strip_edge_hallucinations(
                result.text,
                self.config.transcription.edge_hallucinations,
            )
            transcript = normalize_transcript_newlines(transcript)
            spoken_punctuation: list[str] = []
            if self.config.transcription.spoken_punctuation:
                transcript, spoken_punctuation = apply_spoken_punctuation(
                    transcript,
                    self.config.transcription.spoken_punctuation_replacements,
                )
            if removed_hallucinations:
                self.logger.info(
                    "Removed likely edge hallucination(s): %s",
                    ", ".join(removed_hallucinations),
                )
            if spoken_punctuation:
                self.logger.info(
                    "Applied spoken punctuation: %s",
                    ", ".join(spoken_punctuation),
                )

            job.write_text(job.final_transcript_path, transcript)
            chars_per_min = (len(transcript) / duration_s * 60) if duration_s > 0 else 0
            self.logger.info(
                "Transcription completed in %.2fs (%d chars, %.0f chars/min of audio)",
                result.elapsed_seconds,
                len(transcript),
                chars_per_min,
            )
            if duration_s >= 30 and chars_per_min < self._min_chars_per_minute:
                self.logger.warning(
                    "Low transcript density (%.0f chars/min, expected ~400+ for continuous speech). "
                    "Whisper may have skipped quiet/pause segments. "
                    "Try review mode, speak closer to mic, or lower transcription.no_speech_threshold.",
                    chars_per_min,
                )

            job.update(
                status="routing",
                final_transcript_path=str(job.final_transcript_path),
                transcript_characters=len(transcript),
                transcript_chars_per_minute=chars_per_min,
                spoken_punctuation_commands=spoken_punctuation,
            )

            try:
                routed = False
                if not transcript:
                    self.logger.warning("Transcript empty after post-processing; skipping routing")
                elif mode is not None:
                    route_result = self.router.route(
                        transcript,
                        mode,
                        destination_snapshot=destination_snapshot,
                    )
                    routed = True
                    job.update(
                        route_requested_mode=(
                            requested_mode.value if requested_mode is not None else None
                        ),
                        route_actual_mode=route_result.actual_mode.value,
                        route_fallback_reason=route_result.fallback_reason,
                        route_review_path=route_result.review_path,
                    )
                job.update(
                    status="completed",
                    routed=routed,
                    route_completed_at=utc_now_iso(),
                )
            except Exception as exc:
                job.update(
                    status="route_failed",
                    last_error=str(exc),
                    last_exception_type=type(exc).__name__,
                    failed_at=utc_now_iso(),
                )
                self.logger.exception("Routing failed for dictation job %s: %s", job.job_id, exc)
                self.feedback.route_failed()
                return False

            self.feedback.transcription_complete()
            return True

        return False

    def _attempt_models(self) -> list[str]:
        models = [self.config.transcription.model]
        models.extend([self.config.transcription.model] * max(0, self.config.transcription.retry_count))
        fallback_model = self.config.transcription.fallback_model
        if (
            self.config.transcription.retry_with_smaller_model
            and fallback_model
            and fallback_model != self.config.transcription.model
        ):
            models.append(fallback_model)
        return models

    def _recover_unfinished_jobs(self) -> None:
        jobs = self.job_store.recoverable_jobs()
        if not jobs:
            return

        with self._lock:
            if self.recorder.is_recording or self._processing:
                self.logger.info("Deferring unfinished job recovery because dictation is busy")
                return
            self._processing = True
            self._processing_started_at = time.monotonic()
            self._recovering = True

        self.logger.info("Recovering %d unfinished dictation job(s)", len(jobs))
        self._write_activity_state("processing")
        try:
            for job in jobs:
                if job.status in {"starting", "recording"} and not job.audio_path.is_file():
                    if self._recover_streamed_recording(job):
                        self.feedback.job_recovered()
                        with self._transcription_lock:
                            self._process_job(job, recovered=True)
                        continue
                    recovery_failure = str(job.data.get("raw_recording_recovery_failure") or "")
                    if recovery_failure == "empty":
                        last_error = "App exited before recording captured any audio frames"
                    elif recovery_failure == "missing":
                        last_error = "App exited before recording produced a raw audio sidecar"
                    else:
                        last_error = "App exited before recording produced an audio file"
                    should_alert = bool(job.data.get("alert_on_unrecoverable"))
                    job.update(
                        status="failed_terminal",
                        last_error=last_error,
                        failed_at=utc_now_iso(),
                    )
                    if should_alert:
                        raw_audio_path = job.data.get("recording_raw_path") or job.job_dir / "audio.raw"
                        publish_unrecoverable_recording_alert(
                            job,
                            reason="recording_missing_audio_after_restart",
                            details=(
                                f"{last_error}.\n\n"
                                f"Job: {job.job_id}\n"
                                f"Job path: {job.job_dir}\n"
                                f"Expected audio path: {job.audio_path}\n\n"
                                f"Raw audio path: {raw_audio_path}\n\n"
                                f"Raw audio bytes: {job.data.get('raw_recording_size_bytes', 'unknown')}\n\n"
                                "Home Services could not find a finalized WAV or usable streamed raw "
                                "audio sidecar for this recording, so it cannot retry transcription "
                                "for this dictation."
                            ),
                            logger=self.logger,
                        )
                        self.logger.error("%s for job %s; user alert written", last_error, job.job_id)
                    else:
                        self.logger.warning("%s for stale job %s; marked terminal", last_error, job.job_id)
                    continue
                self.feedback.job_recovered()
                with self._transcription_lock:
                    self._process_job(job, recovered=True)
        finally:
            with self._lock:
                self._processing = False
                self._processing_started_at = None
                self._recovering = False
                if self.recorder.is_recording:
                    next_state = "recording"
                else:
                    next_state = "idle"
            self._write_activity_state(next_state)

    def _recover_streamed_recording(self, job: DictationJob) -> bool:
        raw_path = Path(str(job.data.get("recording_raw_path") or job.job_dir / "audio.raw"))
        if not raw_path.is_file():
            job.update(
                raw_recording_path=str(raw_path),
                raw_recording_recovery_failure="missing",
                raw_recording_recovery_failed_at=utc_now_iso(),
            )
            return False

        raw_size = raw_path.stat().st_size
        if raw_size == 0:
            job.update(
                raw_recording_path=str(raw_path),
                raw_recording_size_bytes=raw_size,
                raw_recording_recovery_failure="empty",
                raw_recording_recovery_failed_at=utc_now_iso(),
            )
            return False

        sample_rate = int(job.data.get("audio_sample_rate") or self.config.audio.sample_rate)
        channels = int(job.data.get("audio_channels") or self.config.audio.channels)
        try:
            finalize_raw_recording_to_wav(raw_path, job.audio_path, sample_rate, channels)
            duration_s = sf.info(str(job.audio_path)).duration
        except Exception as exc:
            self.logger.exception("Failed to recover streamed raw recording for job %s: %s", job.job_id, exc)
            job.update(
                last_error=f"Failed to recover streamed raw recording: {exc}",
                raw_recording_recovery_failed_at=utc_now_iso(),
            )
            return False

        job.update(
            status="recorded",
            audio_file_path=str(job.audio_path),
            recovered_from_streamed_raw_path=str(raw_path),
            recovered_audio_duration_seconds=duration_s,
            recovered_audio_file_size_bytes=job.audio_path.stat().st_size,
        )
        self.logger.warning(
            "Recovered unfinished recording for job %s from streamed raw audio: %s",
            job.job_id,
            raw_path,
        )
        return True

    def _prewarm_audio(self) -> None:
        try:
            self._new_recorder().prewarm()
            self.logger.info("Audio input prewarm completed")
        except Exception as exc:
            self.logger.warning("Audio input prewarm failed: %s", exc)

    def _write_activity_state(self, state: str) -> None:
        try:
            ensure_app_dirs()
            tmp_path = STATE_FILE.with_suffix(".tmp")
            tmp_path.write_text(f"{state}\n", encoding="utf-8")
            tmp_path.replace(STATE_FILE)
        except OSError as exc:
            self.logger.warning("Failed to write dictation activity state: %s", exc)

    def _stop_recorder_with_timeout(self) -> Path:
        timeout_s = self.config.transcription.recording_stop_timeout_seconds
        result_queue: queue.Queue[tuple[str, Path | BaseException]] = queue.Queue(maxsize=1)
        recorder = self.recorder

        def stop_recorder() -> None:
            try:
                result_queue.put(("ok", recorder.stop()))
            except BaseException as exc:  # noqa: BLE001
                result_queue.put(("error", exc))

        stop_thread = threading.Thread(
            target=stop_recorder,
            name="dictation-recorder-stop",
            daemon=True,
        )
        stop_thread.start()
        stop_thread.join(timeout_s)

        if stop_thread.is_alive():
            message = f"Timed out stopping audio recorder after {timeout_s:.1f}s"
            recoverable_path = getattr(recorder, "recoverable_output_path", None)
            if isinstance(recoverable_path, Path) and recoverable_path.is_file():
                self.logger.critical("%s; using already finalized audio file %s", message, recoverable_path)
                job = self._active_job
                if job is not None:
                    job.update(
                        status="recorded",
                        audio_file_path=str(recoverable_path),
                        last_error=message,
                        stop_timeout_recovered_audio=True,
                        stop_timeout_recovered_at=utc_now_iso(),
                    )
                self.recorder = self._new_recorder()
                return recoverable_path

            self.logger.critical("%s; restarting dictation process", message)
            job = self._active_job
            if job is not None:
                job.update(
                    status="failed_terminal",
                    last_error=f"{message} before recovering an audio file",
                    failed_at=utc_now_iso(),
                    alert_on_unrecoverable=True,
                    unrecoverable_alert_reason="recording_stop_timeout_before_audio_saved",
                )
                publish_unrecoverable_recording_alert(
                    job,
                    reason="recording_stop_timeout_before_audio_saved",
                    details=(
                        f"{message} before Home Services could finalize or recover the recording.\n\n"
                        f"Job: {job.job_id}\n"
                        f"Job path: {job.job_dir}\n"
                        f"Expected audio path: {job.audio_path}\n"
                        f"Raw audio path: {job.data.get('recording_raw_path') or job.job_dir / 'audio.raw'}\n"
                        f"Timeout: {timeout_s:.1f}s\n\n"
                        "The recorder stop call did not return. Home Services killed the dictation "
                        "process so the hotkeys would not stay wedged. The streamed raw audio sidecar "
                        "was also missing or unusable, so there is no recording to transcribe or recover."
                    ),
                    logger=self.logger,
                )
            for handler in self.logger.handlers:
                handler.flush()
            os._exit(75)
            raise TimeoutError(f"Timed out stopping audio recorder after {timeout_s:.1f}s")

        status, payload = result_queue.get_nowait()
        if status == "error":
            raise payload
        return payload

    def _cleanup_recording(self, audio_path: Path | None) -> None:
        if self._keep_recordings or not audio_path or not audio_path.is_file():
            return
        audio_path.unlink(missing_ok=True)

    def _cleanup_old_recordings(self) -> None:
        retention_hours = self.config.transcription.recording_retention_hours
        if retention_hours <= 0:
            return

        cutoff = time.time() - (retention_hours * 60 * 60)
        for audio_path in RECORDINGS_DIR.glob("*.wav"):
            try:
                if audio_path.is_file() and audio_path.stat().st_mtime < cutoff:
                    audio_path.unlink(missing_ok=True)
                    self.logger.info(
                        "Deleted retained recording older than %.1f hours: %s",
                        retention_hours,
                        audio_path,
                    )
            except OSError as exc:
                self.logger.warning("Failed to delete old recording %s: %s", audio_path, exc)

    def run(self) -> None:
        ensure_app_dirs()
        self._write_activity_state("idle")
        self._cleanup_old_recordings()
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
        self.logger.info(
            "Audio input: device=%s sample_rate=%d channels=%d",
            self.config.audio.device if self.config.audio.device is not None else "system-default",
            self.config.audio.sample_rate,
            self.config.audio.channels,
        )

        if not check_accessibility(self.logger):
            self.logger.error("Waiting for Accessibility permission — hotkeys disabled until restart.")

        def force_shutdown(signum, _frame) -> None:  # noqa: ANN001
            self.logger.info("Shutting down")
            try:
                self._hotkeys.stop()
            except Exception:
                self.logger.exception("Failed to stop hotkey listener during shutdown")
            self._write_activity_state("idle")
            os._exit(128 + signum)

        signal.signal(signal.SIGINT, force_shutdown)
        signal.signal(signal.SIGTERM, force_shutdown)

        self._hotkeys.start()
        if self.config.audio.prewarm_on_startup:
            threading.Thread(
                target=self._prewarm_audio,
                name="dictation-audio-prewarm",
                daemon=True,
            ).start()
        threading.Thread(
            target=self._recover_unfinished_jobs,
            name="dictation-job-recovery",
            daemon=True,
        ).start()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            self.logger.info("Shutting down")
        finally:
            try:
                self._hotkeys.stop()
            finally:
                os._exit(130)
