from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import get_settings


def configure_logging(level: str = "INFO") -> None:
    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(settings.log_dir) / "system.stdout.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )
