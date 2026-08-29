from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from research_relay.config import AppConfig
from research_relay.redact import redact_text

_MAX_LOG = 1500


def redact_log_message(message: str, secrets: list[str] | tuple[str, ...] | None) -> str:
    out = message or ""
    for secret in secrets or ():
        if not secret:
            continue
        out = re.sub(re.escape(secret), "[redacted]", out, flags=re.IGNORECASE)
        out = redact_text(out, secret)
    if len(out) > _MAX_LOG:
        out = out[:_MAX_LOG] + "…"
    return out


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [item for item in secrets if item]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact_log_message(rendered, self._secrets)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=True)


def install_logging(
    cfg: AppConfig,
    extra_redactions: list[str] | None = None,
) -> logging.Logger:
    secrets = [cfg.relay.private_address, cfg.gmail.username, *(extra_redactions or [])]
    logger = logging.getLogger("research_relay")
    logger.setLevel(getattr(logging, cfg.logging.level, logging.INFO))
    logger.handlers.clear()
    logger.propagate = True

    log_path = Path(cfg.paths.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    redactor = RedactingFilter(secrets)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=cfg.logging.max_bytes,
        backupCount=cfg.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(redactor)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    stream.addFilter(redactor)

    logger.addHandler(file_handler)
    logger.addHandler(stream)
    logging.getLogger().addFilter(redactor)
    return logger
