from __future__ import annotations

import logging
from dataclasses import dataclass

from dictation_router.config.settings import RoutingMode
from dictation_router.routing.cleaner import clean_transcript
from dictation_router.routing.destination import DestinationSnapshot
from dictation_router.routing.editor import EditorLauncher
from dictation_router.routing.inserter import TextInserter


@dataclass(frozen=True)
class RouteResult:
    requested_mode: RoutingMode
    actual_mode: RoutingMode
    fallback_reason: str | None = None
    review_path: str | None = None


class Router:
    """Route transcript text according to the selected mode."""

    def __init__(
        self,
        inserter: TextInserter,
        editor: EditorLauncher,
        logger: logging.Logger | None = None,
        fallback_to_review_when_not_insertable: bool = False,
        fallback_to_review_on_focus_change: bool = False,
    ) -> None:
        self.inserter = inserter
        self.editor = editor
        self.logger = logger or logging.getLogger("dictation_router")
        self.fallback_to_review_when_not_insertable = fallback_to_review_when_not_insertable
        self.fallback_to_review_on_focus_change = fallback_to_review_on_focus_change

    def route(
        self,
        text: str,
        mode: RoutingMode,
        destination_snapshot: DestinationSnapshot | None = None,
    ) -> RouteResult:
        if mode == RoutingMode.INSERT:
            fallback = self._fallback_reason(destination_snapshot)
            if fallback is not None:
                return self._open_review(text, mode, fallback)
            self.inserter.insert(text)
            self.logger.info("Routing transcript via insert mode (%d chars)", len(text))
            return RouteResult(requested_mode=mode, actual_mode=RoutingMode.INSERT)
        elif mode == RoutingMode.REVIEW:
            return self._open_review(text, mode)
        elif mode == RoutingMode.CLEAN:
            cleaned = clean_transcript(text)
            fallback = self._fallback_reason(destination_snapshot)
            if fallback is not None:
                return self._open_review(cleaned, mode, fallback)
            self.logger.info(
                "Routing cleaned transcript via insert mode (%d -> %d chars)",
                len(text),
                len(cleaned),
            )
            self.inserter.insert(cleaned)
            return RouteResult(requested_mode=mode, actual_mode=RoutingMode.CLEAN)
        else:
            raise ValueError(f"Unknown routing mode: {mode}")

    def _fallback_reason(self, destination_snapshot: DestinationSnapshot | None) -> str | None:
        if not (
            self.fallback_to_review_when_not_insertable
            or self.fallback_to_review_on_focus_change
        ):
            return None

        result = self.inserter.can_insert(
            stop_destination=destination_snapshot,
            require_same_destination=self.fallback_to_review_on_focus_change,
        )
        if result.insertable:
            return None
        if result.reason == "focus_changed":
            return result.reason if self.fallback_to_review_on_focus_change else None
        if not self.fallback_to_review_when_not_insertable:
            return None
        return result.reason

    def _open_review(
        self,
        text: str,
        requested_mode: RoutingMode,
        fallback_reason: str | None = None,
    ) -> RouteResult:
        path = self.editor.open_transcript(text)
        if fallback_reason:
            self.logger.info(
                "Opened transcript for review fallback from %s mode: %s (%s)",
                requested_mode.value,
                path,
                fallback_reason,
            )
        else:
            self.logger.info("Opened transcript for review: %s", path)
        return RouteResult(
            requested_mode=requested_mode,
            actual_mode=RoutingMode.REVIEW,
            fallback_reason=fallback_reason,
            review_path=str(path),
        )
