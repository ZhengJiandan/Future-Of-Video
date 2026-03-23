#!/usr/bin/env python3
"""Kling multi-image-to-video API wrapper."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from jose import jwt

from app.core.config import settings
from app.core.provider_keys import require_kling_credentials

logger = logging.getLogger(__name__)

DEFAULT_KLING_BASE_URL = "https://api-singapore.klingai.com"
DEFAULT_KLING_MODEL = "kling-v1-6"
DEFAULT_KLING_MODE = "std"


@dataclass
class KlingVideoGenerationResponse:
    task_id: str
    status: str
    video_url: str = ""
    cover_url: str = ""
    error_message: str = ""
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class KlingVideoTaskStatus:
    task_id: str
    status: str
    video_url: str = ""
    cover_url: str = ""
    error_message: str = ""
    raw_payload: Optional[Dict[str, Any]] = None


class KlingVideoGenerator:
    def __init__(
        self,
        *,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        model: str = DEFAULT_KLING_MODEL,
        mode: str = DEFAULT_KLING_MODE,
        base_url: Optional[str] = None,
    ) -> None:
        resolved_access_key, resolved_secret_key = require_kling_credentials(
            explicit_access_key=access_key,
            explicit_secret_key=secret_key,
            action_label="调用可灵视频生成",
        )
        self.access_key = resolved_access_key
        self.secret_key = resolved_secret_key
        self.model = model or getattr(settings, "KLING_VIDEO_MODEL", DEFAULT_KLING_MODEL)
        self.mode = mode or getattr(settings, "KLING_VIDEO_MODE", DEFAULT_KLING_MODE)
        self.base_url = (base_url or getattr(settings, "KLING_BASE_URL", DEFAULT_KLING_BASE_URL)).rstrip("/")
        self.debug_logging = bool(getattr(settings, "MODEL_DEBUG_LOGGING", True))
        self.debug_max_chars = int(getattr(settings, "MODEL_DEBUG_MAX_CHARS", 20000))

        self.client = httpx.AsyncClient(
            timeout=300.0,
            headers={
                "Authorization": f"Bearer {self._build_jwt_token()}",
                "Content-Type": "application/json",
            },
        )

    def _build_jwt_token(self) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "iss": self.access_key,
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "nbf": int((now - timedelta(seconds=5)).timestamp()),
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

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
                if lowered in {"image", "base64"} and isinstance(item, str) and len(item) > 80:
                    sanitized[key] = f"<image-bytes length={len(item)}>"
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

    def _log_request(self, *, action: str, payload: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Kling video request | model=%s | mode=%s | action=%s\n%s",
            self.model,
            self.mode,
            action,
            self._json_for_log(payload),
        )

    def _log_response(self, *, action: str, payload: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Kling video response | model=%s | mode=%s | action=%s\n%s",
            self.model,
            self.mode,
            action,
            self._json_for_log(payload),
        )

    def _unwrap_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload

    def _extract_video_url(self, payload: Dict[str, Any]) -> str:
        task_result = payload.get("task_result") or payload.get("result") or {}
        if isinstance(task_result, dict):
            videos = task_result.get("videos") or task_result.get("video_list") or []
            if isinstance(videos, list):
                for item in videos:
                    if isinstance(item, dict):
                        url = str(item.get("url") or item.get("video_url") or item.get("resource") or "").strip()
                        if url:
                            return url
        return str(payload.get("video_url") or "").strip()

    def _extract_cover_url(self, payload: Dict[str, Any]) -> str:
        task_result = payload.get("task_result") or payload.get("result") or {}
        if isinstance(task_result, dict):
            images = task_result.get("images") or task_result.get("covers") or []
            if isinstance(images, list):
                for item in images:
                    if isinstance(item, dict):
                        url = str(item.get("url") or item.get("cover_url") or "").strip()
                        if url:
                            return url
        return str(payload.get("cover_url") or "").strip()

    def _extract_error_message(self, payload: Dict[str, Any]) -> str:
        return str(
            payload.get("task_status_msg")
            or payload.get("error_message")
            or payload.get("message")
            or payload.get("msg")
            or ""
        ).strip()

    async def create_multi_image_video_task(
        self,
        *,
        image_list: List[Dict[str, str]],
        prompt: str,
        negative_prompt: str = "",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        enable_audio: bool = True,
        callback_url: str = "",
        external_task_id: str = "",
    ) -> KlingVideoGenerationResponse:
        body = {
            "model_name": self.model,
            "mode": self.mode,
            "duration": str(duration),
            "aspect_ratio": aspect_ratio,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image_list": image_list,
            "enable_audio": enable_audio,
        }
        if callback_url:
            body["callback_url"] = callback_url
        if external_task_id:
            body["external_task_id"] = external_task_id

        self._log_request(action="create_multi_image_video_task", payload=body)
        response = await self.client.post(f"{self.base_url}/v1/videos/multi-image2video", json=body)
        response.raise_for_status()
        data = response.json()
        self._log_response(action="create_multi_image_video_task", payload=data)

        payload = self._unwrap_payload(data)
        task_id = str(payload.get("task_id") or payload.get("id") or "").strip()
        if not task_id:
            raise RuntimeError(f"可灵返回中缺少 task_id: {data}")

        return KlingVideoGenerationResponse(
            task_id=task_id,
            status=str(payload.get("task_status") or payload.get("status") or "submitted"),
            video_url=self._extract_video_url(payload),
            cover_url=self._extract_cover_url(payload),
            error_message=self._extract_error_message(payload),
            created_at=datetime.now(),
        )

    async def get_task_status(self, task_id: str) -> KlingVideoTaskStatus:
        request_payload = {"task_id": task_id, "url": f"{self.base_url}/v1/videos/multi-image2video/{task_id}"}
        self._log_request(action="get_task_status", payload=request_payload)

        response = await self.client.get(f"{self.base_url}/v1/videos/multi-image2video/{task_id}")
        response.raise_for_status()
        data = response.json()
        self._log_response(action="get_task_status", payload=data)

        payload = self._unwrap_payload(data)
        return KlingVideoTaskStatus(
            task_id=str(payload.get("task_id") or task_id),
            status=str(payload.get("task_status") or payload.get("status") or ""),
            video_url=self._extract_video_url(payload),
            cover_url=self._extract_cover_url(payload),
            error_message=self._extract_error_message(payload),
            raw_payload=payload,
        )

    async def wait_for_completion(
        self,
        task_id: str,
        *,
        poll_interval: int = 5,
        max_wait_time: int = 900,
    ) -> KlingVideoGenerationResponse:
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            status = await self.get_task_status(task_id)
            logger.info("Kling task status | task_id=%s | status=%s", task_id, status.status)

            normalized = status.status.lower()
            if normalized in {"succeed", "succeeded", "completed", "success"}:
                return KlingVideoGenerationResponse(
                    task_id=task_id,
                    status="completed",
                    video_url=status.video_url,
                    cover_url=status.cover_url,
                    error_message=status.error_message,
                    completed_at=datetime.now(),
                )
            if normalized in {"failed", "fail"}:
                return KlingVideoGenerationResponse(
                    task_id=task_id,
                    status="failed",
                    error_message=status.error_message or "Kling task failed",
                )

            await asyncio.sleep(poll_interval)

        return KlingVideoGenerationResponse(
            task_id=task_id,
            status="timeout",
            error_message="等待可灵视频生成超时",
        )

    async def close(self) -> None:
        await self.client.aclose()
