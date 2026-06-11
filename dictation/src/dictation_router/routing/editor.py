from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from dictation_router.config.settings import TRANSCRIPTS_DIR, ensure_app_dirs


class EditorLauncher:
    """Write transcript to disk and open in preferred editor."""

    def __init__(self, preferred_editors: list[str] | None = None) -> None:
        self.preferred_editors = preferred_editors or ["WebStorm", "Rider", "TextEdit"]

    def _running_apps(self) -> set[str]:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name of every process'],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {name.strip() for name in result.stdout.split(", ")}

    def _pick_editor(self) -> str:
        running = self._running_apps()
        for editor in self.preferred_editors:
            if editor in running:
                return editor
        return "TextEdit"

    def open_transcript(self, text: str) -> Path:
        ensure_app_dirs()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = TRANSCRIPTS_DIR / f"{timestamp}.txt"
        path.write_text(text + "\n", encoding="utf-8")

        editor = self._pick_editor()
        subprocess.run(["open", "-a", editor, str(path)], check=False)
        return path
