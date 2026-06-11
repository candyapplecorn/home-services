from __future__ import annotations

import argparse
from pathlib import Path

from dictation_router.app import DictationApp
from dictation_router.config.settings import load_config
from dictation_router.logging_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Whisper dictation router for macOS")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config.yaml",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logging()
    app = DictationApp(config, logger)
    app.run()


if __name__ == "__main__":
    main()
