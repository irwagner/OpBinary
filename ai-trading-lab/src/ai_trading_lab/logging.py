"""Logging JSON estruturado com mascaramento obrigatório de segredos."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from typing import Any, TextIO

_REDACTED = "***REDACTED***"
_SECRET_NAME = (
    r"(?:api[_-]?key|apiKey|client[_-]?secret|clientSecret|"
    r"private[_-]?key|privateKey|access[_-]?token|accessToken|"
    r"refresh[_-]?token|refreshToken|id[_-]?token|idToken|"
    r"auth[_-]?token|authToken|secret|password|passphrase|token|"
    r"credential|authorization|cookie|"
    # SSID é a credencial de sessão das plataformas Quadcode/IQ Option.
    r"ssid|session[_-]?id|sessionId)"
)
_SECRET_KEY = re.compile(_SECRET_NAME, re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    rf"(?P<prefix>[\"']?\b{_SECRET_NAME}\b[\"']?\s*(?:=|:|\bis\b)\s*)"
    r"(?P<value>[^,;\r\n]+)",
    re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)


def sanitize(value: Any, key: str | None = None) -> Any:
    """Mascara valores sensíveis recursivamente antes da serialização."""
    if key and _SECRET_KEY.search(key):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(str(value))


def _sanitize_text(value: str) -> str:
    value = _PRIVATE_KEY_BLOCK.sub(_REDACTED, value)
    value = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}", value
    )
    return _BEARER_TOKEN.sub(_REDACTED, value)


class JsonFormatter(logging.Formatter):
    """Formata registros em uma única linha JSON segura."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": sanitize(record.getMessage()),
            "fields": sanitize(getattr(record, "structured_fields", {})),
        }
        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def configure_structured_logger(name: str, stream: TextIO | None = None) -> logging.Logger:
    """Cria logger isolado, estruturado e sem propagação ao root logger."""
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Registra evento estruturado após sanitizar campos potencialmente secretos."""
    logger.info(sanitize(event), extra={"structured_fields": sanitize(fields)})
