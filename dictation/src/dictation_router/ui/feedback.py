from __future__ import annotations

import subprocess
import threading
from pathlib import Path

SYSTEM_SOUNDS = Path("/System/Library/Sounds")


class AudioFeedback:
    """Play macOS system sounds for recording lifecycle events."""

    def __init__(self, sounds_dir: Path | None = None) -> None:
        self._sounds_dir = sounds_dir or SYSTEM_SOUNDS

    def _play(self, name: str) -> None:
        sound = self._sounds_dir / name
        if not sound.is_file():
            return
        threading.Thread(
            target=subprocess.run,
            args=(["afplay", str(sound)],),
            kwargs={"check": False},
            daemon=True,
        ).start()

    def ack(self) -> None:
        self._play("Morse.aiff")

    def recording_started(self) -> None:
        self._play("Tink.aiff")

    def recording_stopped(self) -> None:
        def _double_beep() -> None:
            for _ in range(2):
                subprocess.run(["afplay", str(self._sounds_dir / "Pop.aiff")], check=False)

        threading.Thread(target=_double_beep, daemon=True).start()

    def transcription_started(self) -> None:
        self._play("Ping.aiff")

    def transcription_complete(self) -> None:
        self._play("Glass.aiff")

    def transcription_failed(self) -> None:
        self.error()

    def transcription_retrying(self) -> None:
        self._play("Submarine.aiff")

    def job_recovered(self) -> None:
        self._play("Hero.aiff")

    def route_failed(self) -> None:
        self.error()

    def error(self) -> None:
        self._play("Basso.aiff")
