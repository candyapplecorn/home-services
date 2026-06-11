from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path) -> str:
        """Return transcript text for the given audio file."""


class WhisperCppTranscriber(Transcriber):
    """Invoke whisper.cpp via subprocess."""

    def __init__(
        self,
        model: str,
        whisper_cli: str = "whisper-cli",
        models_dir: Path | None = None,
        split_on_word: bool = True,
        no_speech_threshold: float = 0.35,
        logprob_threshold: float = -1.0,
    ) -> None:
        self.model = model
        self.whisper_cli = whisper_cli
        self.models_dir = models_dir or Path("~/.cache/whisper-cpp").expanduser()
        self.split_on_word = split_on_word
        self.no_speech_threshold = no_speech_threshold
        self.logprob_threshold = logprob_threshold

    def _model_path(self) -> Path:
        name = self.model if self.model.endswith(".bin") else f"ggml-{self.model}.bin"
        return self.models_dir / name

    def transcribe(self, audio_path: Path) -> str:
        model_path = self._model_path()
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Whisper model not found: {model_path}. "
                f"Download ggml-{self.model}.bin into {self.models_dir}"
            )

        output_prefix = audio_path.with_suffix("")
        cmd = [
            self.whisper_cli,
            "-m",
            str(model_path),
            "-f",
            str(audio_path),
            "-otxt",
            "-of",
            str(output_prefix),
            "-l",
            "en",
            "--no-timestamps",
            "-nth",
            str(self.no_speech_threshold),
            "-lpt",
            str(self.logprob_threshold),
        ]
        if self.split_on_word:
            cmd.append("-sow")

        started = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        elapsed = time.perf_counter() - started

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"whisper-cli failed after {elapsed:.1f}s: {stderr}")

        txt_path = Path(f"{output_prefix}.txt")
        if not txt_path.is_file():
            raise RuntimeError(f"Expected transcript file missing: {txt_path}")

        text = txt_path.read_text(encoding="utf-8").strip()
        txt_path.unlink(missing_ok=True)
        return text
