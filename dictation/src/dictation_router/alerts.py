from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dictation_router.config.settings import ALERTS_DIR, ensure_app_dirs
from dictation_router.jobs import DictationJob, utc_now_iso


def publish_unrecoverable_recording_alert(
    job: DictationJob,
    *,
    reason: str,
    details: str,
    logger: logging.Logger | None = None,
) -> Path | None:
    """Write a durable user-visible alert for a recording that cannot be recovered."""
    try:
        ensure_app_dirs()
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        alert_path = ALERTS_DIR / f"{job.job_id}-unrecoverable-recording.json"
        if alert_path.exists():
            return alert_path

        payload: dict[str, Any] = {
            "id": f"{job.job_id}-unrecoverable-recording",
            "type": "unrecoverable_recording_loss",
            "severity": "error",
            "title": "Dictation Recording Could Not Be Recovered",
            "message": (
                "Home Services crashed while saving a recording. No audio file was written, "
                "so there is no text to recover for that dictation."
            ),
            "reason": reason,
            "details": details,
            "job_id": job.job_id,
            "job_path": str(job.job_dir),
            "created_at": utc_now_iso(),
        }
        tmp_path = alert_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(alert_path)
        return alert_path
    except OSError as exc:
        if logger is not None:
            logger.warning("Failed to write unrecoverable recording alert: %s", exc)
        return None
