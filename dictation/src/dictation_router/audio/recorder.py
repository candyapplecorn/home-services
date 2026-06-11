from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from dictation_router.config.settings import RECORDINGS_DIR, ensure_app_dirs


class AudioRecorder:
    """Capture microphone input to a temporary WAV file."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False
        self._output_path: Path | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:  # noqa: ARG002
        if status:
            pass
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._recording = True

        ensure_app_dirs()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._output_path = RECORDINGS_DIR / f"{timestamp}.wav"

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> Path:
        with self._lock:
            self._recording = False

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            if not self._frames:
                raise RuntimeError("No audio captured")

            audio = np.concatenate(self._frames, axis=0)
            output_path = self._output_path or RECORDINGS_DIR / "recording.wav"

        sf.write(str(output_path), audio, self.sample_rate)
        return output_path
