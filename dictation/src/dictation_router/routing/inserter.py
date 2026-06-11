from __future__ import annotations

import subprocess
import time

from pynput.keyboard import Controller, Key


class TextInserter:
    """Insert text via simulated keyboard typing with clipboard fallback."""

    def __init__(self, max_typing_chars: int = 5000) -> None:
        self.max_typing_chars = max_typing_chars
        self._keyboard = Controller()

    def insert(self, text: str) -> None:
        if not text:
            return

        if len(text) <= self.max_typing_chars:
            try:
                self._type_text(text)
                return
            except Exception:
                pass

        self._clipboard_paste(text)

    def _type_text(self, text: str) -> None:
        time.sleep(0.05)
        for char in text:
            self._keyboard.type(char)

    def _clipboard_paste(self, text: str) -> None:
        saved = self._read_clipboard()
        try:
            self._write_clipboard(text)
            time.sleep(0.05)
            with self._keyboard.pressed(Key.cmd):
                self._keyboard.press("v")
                self._keyboard.release("v")
        finally:
            time.sleep(0.05)
            self._write_clipboard(saved)

    @staticmethod
    def _read_clipboard() -> str:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
        return result.stdout

    @staticmethod
    def _write_clipboard(text: str) -> None:
        subprocess.run(["pbcopy"], input=text, text=True, check=False)
