"""Structured logging (PLAN step 13).

Rotating file log in %APPDATA%/AxonVoice/logs plus console output. Transcript
and audio CONTENTS are banned from logs by default — code logs lengths/metadata,
never the text. An opt-in diagnostic mode (AXON_DIAGNOSTIC=1) is the only way raw
text is recorded, for the user's own troubleshooting.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("APPDATA", "~")).expanduser() / "AxonVoice" / "logs"
LOG_FILE = LOG_DIR / "axon.log"

DIAGNOSTIC = os.environ.get("AXON_DIAGNOSTIC") == "1"

_configured = False


def _make_console_safe() -> None:
    """Stop bare print()/console handlers from crashing the app.

    Two failure modes on Windows: (1) the legacy console codepage (cp1252) can't
    encode non-ASCII like → or — and raises UnicodeEncodeError; (2) under
    pythonw / a windowed PyInstaller build stdout/stderr are None and print()
    raises. Reconfigure to UTF-8 when present, route to devnull when absent.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def setup_logging() -> logging.Logger:
    global _configured
    _make_console_safe()
    logger = logging.getLogger("axon")
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG if DIAGNOSTIC else logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s.%(module)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:  # logging must never crash the app
        print(f"[Axon] could not open log file: {e}")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    _configured = True
    logger.info("Logging started (diagnostic=%s) → %s", DIAGNOSTIC, LOG_FILE)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("axon")


def safe_text_summary(text: str) -> str:
    """How to refer to a Transcript in logs: full text only in diagnostic mode."""
    if DIAGNOSTIC:
        return repr(text)
    return f"<{len(text)} chars>"
