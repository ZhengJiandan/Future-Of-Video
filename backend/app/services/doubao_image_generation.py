#!/usr/bin/env python3
"""豆包 Seedream 图片生成客户端。"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

from app.core.config import settings
from app.core.provider_keys import get_effective_doubao_api_key

DEFAULT_ARK_IMAGE_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_TEXT_TO_IMAGE_MODEL = "doubao-seedream-4-0-250828"
DEFAULT_ARK_IMAGE_EDIT_MODEL = "doubao-seededit-3-0-i2i-250628"


class DoubaoImageGenerationClient:
    """火山引擎豆包 Seedream 图片生成客户端。

    参考官方文档：
    https://www.volcengine.com/docs/82379/1824121?lang=zh
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (
            base_url
            or getattr(settings, "DOUBAO_IMAGE_BASE_URL", None)
            or "https://operator.las.cn-beijing.volces.com/api/v1"
        ).rstrip("/")
        self.ark_base_url = (
            getattr(settings, "DOUBAO_BASE_URL", None)
            or DEFAULT_ARK_IMAGE_BASE_URL
        ).rstrip("/")
        self.model = model or getattr(settings, "DOUBAO_IMAGE_MODEL", "doubao-seedream-5-0-260128")
        self.debug_logging = bool(getattr(settings, "MODEL_DEBUG_LOGGING", True))
        self.debug_max_chars = int(getattr(settings, "MODEL_DEBUG_MAX_CHARS", 20000))
        self.timeout = max(30, int(float(getattr(settings, "DOUBAO_READ_TIMEOUT", 240.0))))
        self.endpoint_candidates = [
            (self.base_url, "/online/images/generations", "default"),
            (self.base_url, "/images/generations", "default"),
            (self.ark_base_url, "/images/generations", "ark-compatible"),
        ]

    @property
    def configured(self) -> bool:
        return bool(get_effective_doubao_api_key(self.api_key))

    def _headers(self) -> Dict[str, str]:
        api_key = get_effective_doubao_api_key(self.api_key)
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _truncate_for_log(self, value: str) -> str:
        if len(value) <= self.debug_max_chars:
            return value
        return f"{value[:self.debug_max_chars]}\n...<truncated {len(value) - self.debug_max_chars} chars>"

    def _sanitize_for_log(self, value: Any, *, parent_key: str = "") -> Any:
        if isinstance(value, dict):
            sanitized: Dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered == "authorization":
                    sanitized[key] = "***"
                    continue
                if lowered in {"image", "b64_json"}:
                    if isinstance(item, list):
                        sanitized[key] = [self._sanitize_for_log(sub_item, parent_key=lowered) for sub_item in item]
                    elif isinstance(item, str):
                        sanitized[key] = f"<string length={len(item)}>"
                    else:
                        sanitized[key] = item
                    continue
                sanitized[key] = self._sanitize_for_log(item, parent_key=lowered)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_for_log(item, parent_key=parent_key) for item in value]
        if isinstance(value, str):
            return self._truncate_for_log(value)
        return value

    def _json_for_log(self, payload: Any) -> str:
        try:
            raw = json.dumps(self._sanitize_for_log(payload), ensure_ascii=False, indent=2)
        except Exception:
            raw = str(payload)
        return self._truncate_for_log(raw)

    def _log_request(self, *, url: str, payload: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Doubao image request | model={} | url={} | timeout={}s\n{}",
            payload.get("model") or self.model,
            url,
            self.timeout,
            self._json_for_log(payload),
        )

    def _log_response(self, *, response_body: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Doubao image response | model={}\n{}",
            self.model,
            self._json_for_log(response_body),
        )

    def _resolve_payload_for_candidate(self, payload: Dict[str, Any], strategy: str) -> Dict[str, Any]:
        candidate_payload = dict(payload)
        if strategy != "ark-compatible":
            return candidate_payload

        has_image_input = bool(candidate_payload.get("image"))
        candidate_payload["model"] = (
            DEFAULT_ARK_IMAGE_EDIT_MODEL if has_image_input else DEFAULT_ARK_TEXT_TO_IMAGE_MODEL
        )
        return candidate_payload

    def _normalize_size(self, *, aspect_ratio: str, image_size: str) -> str:
        presets = {
            "1k": 1024,
            "2k": 2048,
            "3k": 3072,
            "4k": 3072,
        }
        base = presets.get(str(image_size or "").strip().lower(), 2048)
        ratio_map = {
            "1:1": (1, 1),
            "16:9": (16, 9),
            "9:16": (9, 16),
            "4:3": (4, 3),
            "3:4": (3, 4),
        }
        width_ratio, height_ratio = ratio_map.get(str(aspect_ratio or "").strip(), (16, 9))
        if width_ratio >= height_ratio:
            width = base
            height = max(512, int(round(base * height_ratio / width_ratio / 32)) * 32)
        else:
            height = base
            width = max(512, int(round(base * width_ratio / height_ratio / 32)) * 32)
        return f"{width}x{height}"

    def _image_path_to_data_uri(self, image_path: str) -> str:
        path = Path(image_path)
        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _call_api(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            return {
                "success": False,
                "error": "DOUBAO_API_KEY not configured",
            }

        last_error = "Doubao image generation failed"
        for base_url, endpoint, strategy in self.endpoint_candidates:
            url = f"{base_url}{endpoint}"
            request_payload = self._resolve_payload_for_candidate(payload, strategy)
            try:
                self._log_request(url=url, payload=request_payload)
                response = requests.post(
                    url,
                    headers=self._headers(),
                    json=request_payload,
                    timeout=self.timeout,
                )
                if response.status_code in {401, 403, 404, 405}:
                    last_error = f"API Error: {response.status_code} - {response.text[:200]}"
                    continue
                if response.status_code != 200:
                    last_error = f"API Error: {response.status_code} - {response.text[:200]}"
                    logger.error(last_error)
                    return {
                        "success": False,
                        "error": last_error,
                    }

                result = response.json()
                self._log_response(response_body=result)
                data_list = result.get("data") or []
                if not data_list:
                    return {
                        "success": False,
                        "error": "Doubao image response missing data",
                    }

                first_item = data_list[0] or {}
                image_b64 = str(first_item.get("b64_json") or "").strip()
                if image_b64:
                    return {
                        "success": True,
                        "image_data": base64.b64decode(image_b64),
                        "image_b64": image_b64,
                        "image_url": "",
                        "error": "",
                    }

                image_url = str(first_item.get("url") or "").strip()
                if image_url:
                    image_response = requests.get(image_url, timeout=self.timeout)
                    image_response.raise_for_status()
                    return {
                        "success": True,
                        "image_data": image_response.content,
                        "image_b64": "",
                        "image_url": image_url,
                        "error": "",
                    }

                return {
                    "success": False,
                    "error": "Doubao image response missing b64_json/url",
                }
            except Exception as exc:
                last_error = f"Request failed: {exc}"
                logger.error(last_error)

        return {
            "success": False,
            "error": last_error,
        }

    def generate_text_to_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k",
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": self._normalize_size(aspect_ratio=aspect_ratio, image_size=image_size),
            "response_format": "b64_json",
            "watermark": False,
        }
        return self._call_api(payload)

    def generate_image_to_image(
        self,
        input_image_path: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k",
    ) -> Dict[str, Any]:
        return self.generate_multi_image_mix(
            [input_image_path],
            prompt,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        )

    def generate_multi_image_mix(
        self,
        input_image_paths: List[str],
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k",
    ) -> Dict[str, Any]:
        normalized_paths = [str(item).strip() for item in input_image_paths if str(item).strip()]
        if not normalized_paths:
            return self.generate_text_to_image(prompt, aspect_ratio=aspect_ratio, image_size=image_size)

        images = [self._image_path_to_data_uri(item) for item in normalized_paths]
        payload = {
            "model": self.model,
            "prompt": prompt,
            "image": images[0] if len(images) == 1 else images,
            "size": self._normalize_size(aspect_ratio=aspect_ratio, image_size=image_size),
            "response_format": "b64_json",
            "watermark": False,
        }
        return self._call_api(payload)
