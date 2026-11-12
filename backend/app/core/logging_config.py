"""
Logging for MYMILE's own modules (the "app.*" loggers).

Uvicorn configures only its own loggers, so INFO messages from app modules (for
example the Groq token-usage lines) were silently dropped. configure_logging()
adds ONE stream handler to the "app" logger, unless the root logger already has a
handler (then records propagate there and are printed once). It never touches
Uvicorn's loggers or access log, and it is safe to call repeatedly (reloads, tests).

A redaction filter masks API-key-like strings, bearer tokens and organization ids
in every message this handler prints, as a second line of defense: the code already
never logs keys, prompts or product payloads.
"""
import logging
import re
import sys
from typing import Optional, TextIO

HANDLER_NAME = "mymile-app"
LOGGER_NAME = "app"
FORMAT = "%(levelname)s:     %(name)s - %(message)s"

_SECRET = re.compile(r"\b(gsk[_-]|sk-|AIza)[A-Za-z0-9_\-]{4,}|\bBearer\s+[A-Za-z0-9._\-]+|\borg_[A-Za-z0-9]+",
                     re.I)


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: m.group(0)[:4] + "***", text)


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a malformed record must not break logging
            return True
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def _level(value) -> int:
    level = logging.getLevelName(str(value or "INFO").strip().upper())
    return level if isinstance(level, int) else logging.INFO


def configure_logging(level: Optional[str] = "INFO", stream: Optional[TextIO] = None) -> Optional[logging.Handler]:
    """Make app.* records at `level` and above visible. Returns MYMILE's handler, or None
    when the root logger already prints (no second handler, so no duplicate lines)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_level(level))
    existing = next((h for h in logger.handlers if h.get_name() == HANDLER_NAME), None)
    if existing is not None:
        return existing
    if logging.getLogger().handlers:
        return None
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(RedactSecrets())
    logger.addHandler(handler)
    return handler
