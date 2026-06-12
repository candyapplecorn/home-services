from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path) -> str:
        """Return transcript text for the given audio file."""


@dataclass(frozen=True)
class TranscriptionRunResult:
    text: str
    command: list[str]
    model: str
    model_path: Path
    output_prefix: Path
    transcript_path: Path
    started_at: str
    ended_at: str
    elapsed_seconds: float
    exit_code: int
    stdout: str
    stderr: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "whisper_command": self.command,
            "model": self.model,
            "model_path": str(self.model_path),
            "output_prefix": str(self.output_prefix),
            "transcript_path": str(self.transcript_path),
            "transcription_started_at": self.started_at,
            "transcription_ended_at": self.ended_at,
            "transcription_elapsed_seconds": self.elapsed_seconds,
            "exit_code": self.exit_code,
        }


class WhisperCppError(RuntimeError):
    def __init__(self, message: str, result: TranscriptionRunResult) -> None:
        super().__init__(message)
        self.result = result


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
        threads: int = 4,
        processors: int = 1,
        metal: bool = True,
    ) -> None:
        self.model = model
        self.whisper_cli = whisper_cli
        self.models_dir = models_dir or Path("~/.cache/whisper-cpp").expanduser()
        self.split_on_word = split_on_word
        self.no_speech_threshold = no_speech_threshold
        self.logprob_threshold = logprob_threshold
        self.threads = threads
        self.processors = processors
        self.metal = metal

    def _model_path(self, model: str | None = None) -> Path:
        model_name = model or self.model
        name = model_name if model_name.endswith(".bin") else f"ggml-{model_name}.bin"
        return self.models_dir / name

    def _command(self, audio_path: Path, output_prefix: Path, model: str | None = None) -> list[str]:
        model_name = model or self.model
        model_path = self._model_path(model_name)
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Whisper model not found: {model_path}. "
                f"Download ggml-{model_name}.bin into {self.models_dir}"
            )

        cmd = [
            self.whisper_cli,
            "-m",
            str(model_path),
            "-f",
            str(audio_path),
            "-t",
            str(self.threads),
            "-p",
            str(self.processors),
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
        if not self.metal:
            cmd.append("-ng")
        return cmd

    def transcribe_detailed(
        self,
        audio_path: Path,
        output_prefix: Path | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        model: str | None = None,
    ) -> TranscriptionRunResult:
        model_name = model or self.model
        model_path = self._model_path(model_name)
        output_prefix = output_prefix or audio_path.with_suffix("")
        cmd = self._command(audio_path, output_prefix, model_name)
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        elapsed = time.perf_counter() - started
        ended_at = datetime.now(UTC).isoformat()
        transcript_path = Path(f"{output_prefix}.txt")

        if stdout_path is not None:
            stdout_path.write_text(result.stdout, encoding="utf-8")
        if stderr_path is not None:
            stderr_path.write_text(result.stderr, encoding="utf-8")

        run_result = TranscriptionRunResult(
            text="",
            command=cmd,
            model=model_name,
            model_path=model_path,
            output_prefix=output_prefix,
            transcript_path=transcript_path,
            started_at=started_at,
            ended_at=ended_at,
            elapsed_seconds=elapsed,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise WhisperCppError(f"whisper-cli failed after {elapsed:.1f}s: {stderr}", run_result)

        if not transcript_path.is_file():
            raise WhisperCppError(f"Expected transcript file missing: {transcript_path}", run_result)

        text = transcript_path.read_text(encoding="utf-8").strip()
        return TranscriptionRunResult(
            text=text,
            command=cmd,
            model=model_name,
            model_path=model_path,
            output_prefix=output_prefix,
            transcript_path=transcript_path,
            started_at=started_at,
            ended_at=ended_at,
            elapsed_seconds=elapsed,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def transcribe(self, audio_path: Path) -> str:
        result = self.transcribe_detailed(audio_path)
        result.transcript_path.unlink(missing_ok=True)
        return result.text
