from __future__ import annotations

import logging

from dictation_router.config.settings import RoutingMode
from dictation_router.routing.cleaner import clean_transcript
from dictation_router.routing.editor import EditorLauncher
from dictation_router.routing.inserter import TextInserter


class Router:
    """Route transcript text according to the selected mode."""

    def __init__(
        self,
        inserter: TextInserter,
        editor: EditorLauncher,
        logger: logging.Logger | None = None,
    ) -> None:
        self.inserter = inserter
        self.editor = editor
        self.logger = logger or logging.getLogger("dictation_router")

    def route(self, text: str, mode: RoutingMode) -> None:
        if mode == RoutingMode.INSERT:
            self.logger.info("Routing transcript via insert mode (%d chars)", len(text))
            self.inserter.insert(text)
        elif mode == RoutingMode.REVIEW:
            path = self.editor.open_transcript(text)
            self.logger.info("Opened transcript for review: %s", path)
        elif mode == RoutingMode.CLEAN:
            cleaned = clean_transcript(text)
            self.logger.info(
                "Routing cleaned transcript via insert mode (%d -> %d chars)",
                len(text),
                len(cleaned),
            )
            self.inserter.insert(cleaned)
        else:
            raise ValueError(f"Unknown routing mode: {mode}")
