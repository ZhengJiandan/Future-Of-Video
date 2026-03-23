from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.request_runtime import get_request_doubao_api_key


DOUBAO_API_KEY_ERROR_CODE = "missing_doubao_api_key"


@dataclass
class MissingProviderConfigError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def get_effective_doubao_api_key(explicit_api_key: Optional[str] = None) -> Optional[str]:
    for candidate in (
        explicit_api_key,
        get_request_doubao_api_key(),
        getattr(settings, "DOUBAO_API_KEY", None),
        os.getenv("DOUBAO_API_KEY"),
    ):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return None


def require_doubao_api_key(
    *,
    explicit_api_key: Optional[str] = None,
    action_label: str = "调用豆包能力",
) -> str:
    api_key = get_effective_doubao_api_key(explicit_api_key)
    if api_key:
        return api_key
    raise MissingProviderConfigError(
        code=DOUBAO_API_KEY_ERROR_CODE,
        message=f"未配置 DOUBAO_API_KEY，无法{action_label}。可在前端临时填写后重试。",
    )
