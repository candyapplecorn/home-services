from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import BinaryIO
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from dictation_router.config.settings import RECORDINGS_DIR, ensure_app_dirs


class AudioRecorder:
    """Capture microphone input to a durable WAV file."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1, device: int | str | None = None) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False
        self._output_path: Path | None = None
        self._raw_path: Path | None = None
        self._raw_file: BinaryIO | None = None
        self._captured_frames = 0
        self._write_error: str | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def raw_path(self) -> Path | None:
        with self._lock:
            return self._raw_path

    @property
    def recoverable_output_path(self) -> Path | None:
        with self._lock:
            output_path = self._output_path
            raw_path = self._raw_path

        if output_path is not None and output_path.is_file():
            return output_path
        if output_path is None or raw_path is None or not raw_path.is_file():
            return None
        try:
            finalize_raw_recording_to_wav(raw_path, output_path, self.sample_rate, self.channels)
        except Exception:
            return None
        return output_path if output_path.is_file() else None

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:  # noqa: ARG002
        if status:
            pass
        with self._lock:
            if not self._recording or self._raw_file is None:
                return
            try:
                self._raw_file.write(np.ascontiguousarray(indata, dtype=np.float32).tobytes())
                self._captured_frames += frames
            except Exception as exc:
                self._write_error = str(exc)
                self._recording = False

    def start(self, output_path: Path | None = None) -> None:
        ensure_app_dirs()
        if output_path is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_path = RECORDINGS_DIR / f"{timestamp}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path = output_path.with_suffix(".raw")
        output_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)

        with self._lock:
            if self._recording:
                return
            self._output_path = output_path
            self._raw_path = raw_path
            self._raw_file = raw_path.open("wb", buffering=0)
            self._captured_frames = 0
            self._write_error = None
            self._recording = True

        try:
            self._stream = sd.InputStream(
                device=self.device,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            self._close_raw_file()
            with self._lock:
                self._recording = False
            raise

    def prewarm(self) -> None:
        stream: sd.InputStream | None = None
        try:
            stream = sd.InputStream(
                device=self.device,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
            )
            stream.start()
            time.sleep(0.05)
            stream.abort()
        finally:
            if stream is not None:
                stream.close()

    def stop(self) -> Path:
        with self._lock:
            self._recording = False
            output_path = self._output_path
            raw_path = self._raw_path
            captured_frames = self._captured_frames
            write_error = self._write_error

        self._close_raw_file()

        if output_path is None or raw_path is None:
            raise RuntimeError("Recording output path was not initialized")
        if not raw_path.is_file() or raw_path.stat().st_size == 0 or captured_frames <= 0:
            raise RuntimeError("No audio captured")
        finalize_raw_recording_to_wav(raw_path, output_path, self.sample_rate, self.channels)
        if write_error and not output_path.is_file():
            raise RuntimeError(f"Audio write failed: {write_error}")

        if self._stream is not None:
            stream = self._stream
            self._stream = None
            stream.abort()
            stream.close()

        return output_path

    def _close_raw_file(self) -> None:
        with self._lock:
            raw_file = self._raw_file
            self._raw_file = None

        if raw_file is not None:
            raw_file.flush()
            raw_file.close()


def finalize_raw_recording_to_wav(
    raw_path: Path,
    output_path: Path,
    sample_rate: int,
    channels: int,
) -> Path:
    """Convert the streamed float32 PCM sidecar into a WAV file."""
    if channels <= 0:
        raise ValueError("channels must be positive")
    audio = np.fromfile(raw_path, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError(f"No audio captured in raw recording: {raw_path}")
    complete_samples = (audio.size // channels) * channels
    if complete_samples == 0:
        raise RuntimeError(f"Raw recording has no complete frames: {raw_path}")
    if complete_samples != audio.size:
        audio = audio[:complete_samples]
    audio = audio.reshape((-1, channels))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), audio, sample_rate)
    return output_path
