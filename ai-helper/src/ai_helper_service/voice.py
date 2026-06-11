from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from .config import Settings

APP_SUPPORT = Path.home() / "Library/Application Support/HomeServices/ai-helper"
RECORDINGS_DIR = APP_SUPPORT / "recordings"


class MissingVoiceRuntime(RuntimeError):
    pass


def _model_path(settings: Settings) -> Path:
    models_dir = Path(settings.whisper_models_dir).expanduser()
    name = (
        settings.whisper_model
        if settings.whisper_model.endswith(".bin")
        else f"ggml-{settings.whisper_model}.bin"
    )
    return models_dir / name


def record_until_enter(settings: Settings) -> Path:
    try:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
    except ImportError as error:
        raise MissingVoiceRuntime(
            "Missing voice dependencies. Run: "
            'cd ~/bin/home-services/ai-helper && .venv/bin/python -m pip install -e ".[local,voice,dev]"'
        ) from error

    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = RECORDINGS_DIR / f"{timestamp}.wav"
    frames: list[np.ndarray] = []

    def callback(indata: np.ndarray, _frames: int, _time, _status) -> None:
        frames.append(indata.copy())

    input("Press Enter to start recording...")
    print("Recording. Press Enter to stop.", flush=True)
    with sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="float32",
        callback=callback,
    ):
        input()

    if not frames:
        raise RuntimeError("No audio captured")

    audio = np.concatenate(frames, axis=0)
    sf.write(str(output_path), audio, 16000)
    return output_path


def transcribe(audio_path: Path, settings: Settings) -> str:
    model_path = _model_path(settings)
    if not model_path.is_file():
        raise FileNotFoundError(
            f"Whisper model not found: {model_path}. "
            "Run ./install.sh --download-model or set AI_HELPER_WHISPER_MODEL."
        )

    output_prefix = audio_path.with_suffix("")
    cmd = [
        settings.whisper_cli,
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
        "0.35",
        "-lpt",
        "-1.0",
        "-sow",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"whisper-cli failed: {stderr}")

    txt_path = Path(f"{output_prefix}.txt")
    if not txt_path.is_file():
        raise RuntimeError(f"Expected transcript file missing: {txt_path}")

    transcript = txt_path.read_text(encoding="utf-8").strip()
    txt_path.unlink(missing_ok=True)
    return transcript


def prompt_from_voice(settings: Settings) -> str:
    audio_path = record_until_enter(settings)
    print(f"Transcribing {audio_path.name}...", flush=True)
    transcript = transcribe(audio_path, settings)
    print(f"Transcript: {transcript}", flush=True)
    audio_path.unlink(missing_ok=True)
    return transcript
