from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_request_doubao_api_key: ContextVar[Optional[str]] = ContextVar("request_doubao_api_key", default=None)


def set_request_doubao_api_key(api_key: Optional[str]) -> Token:
    normalized = str(api_key or "").strip() or None
    return _request_doubao_api_key.set(normalized)


def reset_request_doubao_api_key(token: Token) -> None:
    _request_doubao_api_key.reset(token)


def get_request_doubao_api_key() -> Optional[str]:
    return _request_doubao_api_key.get()
