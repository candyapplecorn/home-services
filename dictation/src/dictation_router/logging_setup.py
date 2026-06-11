from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from dictation_router.config.settings import LOGS_DIR, ensure_app_dirs


def setup_logging() -> logging.Logger:
    ensure_app_dirs()
    logger = logging.getLogger("dictation_router")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    log_file = LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(console)
    return logger
