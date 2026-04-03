#!/usr/bin/env python3
"""Kling API client for video, subject, and voice endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx
from jose import jwt

from app.core.config import settings
from app.core.provider_keys import require_kling_credentials

logger = logging.getLogger(__name__)

DEFAULT_KLING_BASE_URL = "https://api-beijing.klingai.com"
DEFAULT_KLING_MODEL = "kling-v3-omni"
DEFAULT_KLING_MODE = "std"
SUPPORTED_KLING_VIDEO_MODELS = {"kling-video-o1", "kling-v3-omni"}
SUPPORTED_KLING_OMNI_MODELS = {"kling-video-o1", "kling-v3-omni"}
SUPPORTED_KLING_VIDEO_MODES = {"std", "pro"}
SUPPORTED_KLING_ASPECT_RATIOS = {"16:9", "9:16", "1:1"}
SUPPORTED_KLING_SOUND_OPTIONS = {"on", "off"}
SUPPORTED_KLING_MULTI_SHOT_TYPES = {"customize", "intelligence"}
SUPPORTED_KLING_IMAGE_REFERENCE_TYPES = {"first_frame", "end_frame"}
SUPPORTED_KLING_VIDEO_REFER_TYPES = {"feature", "base"}
SUPPORTED_KLING_KEEP_ORIGINAL_SOUND = {"yes", "no"}

VIDEO_TASK_OMNI_GENERATION = "omni_generation"
RUNNING_VIDEO_TASK_STATUSES = {"submitted", "processing", "queued", "running", "pending"}
SUCCESS_VIDEO_TASK_STATUSES = {"succeed", "succeeded", "completed", "success"}
FAILED_VIDEO_TASK_STATUSES = {"failed", "fail"}


@dataclass
class KlingVideoGenerationResponse:
    task_id: str
    status: str
    video_url: str = ""
    cover_url: str = ""
    error_message: str = ""
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    raw_payload: Optional[Dict[str, Any]] = None


@dataclass
class KlingVideoTaskStatus:
    task_id: str
    status: str
    video_url: str = ""
    cover_url: str = ""
    error_message: str = ""
    raw_payload: Optional[Dict[str, Any]] = None


class KlingAPIClient:
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
            action_label="调用可灵接口",
        )
        self.access_key = resolved_access_key
        self.secret_key = resolved_secret_key
        self.model = model or getattr(settings, "KLING_VIDEO_MODEL", DEFAULT_KLING_MODEL)
        self.mode = mode or getattr(settings, "KLING_VIDEO_MODE", DEFAULT_KLING_MODE)
        self.base_url = (base_url or getattr(settings, "KLING_BASE_URL", DEFAULT_KLING_BASE_URL)).rstrip("/")
        self.debug_logging = bool(getattr(settings, "MODEL_DEBUG_LOGGING", False))
        self.debug_max_chars = int(getattr(settings, "MODEL_DEBUG_MAX_CHARS", 20000))
        self.client = httpx.AsyncClient(
            timeout=300.0,
            headers={
                "Authorization": f"Bearer {self._build_jwt_token()}",
                "Content-Type": "application/json",
            },
        )

    def _normalize_model_name(self, model_name: str) -> str:
        normalized = str(model_name or "").strip()
        if not normalized:
            return DEFAULT_KLING_MODEL
        if normalized in SUPPORTED_KLING_VIDEO_MODELS:
            return normalized
        logger.warning("Unsupported Kling video model requested, fallback to %s: %s", DEFAULT_KLING_MODEL, model_name)
        return DEFAULT_KLING_MODEL

    def _is_omni_model(self, model_name: str) -> bool:
        return self._normalize_model_name(model_name) in SUPPORTED_KLING_OMNI_MODELS

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
                if lowered in {"image", "audio_file", "audio", "base64"} and isinstance(item, str) and len(item) > 80:
                    sanitized[key] = f"<binary-like-bytes length={len(item)}>"
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

    def _extract_http_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json() if response.content else {}
        except Exception:
            text = response.text.strip()
            return text

        if isinstance(payload, dict):
            unwrapped = self._unwrap_payload(payload)
            detail = self._extract_error_message(unwrapped) or self._extract_error_message(payload)
            if detail:
                return detail
            return json.dumps(payload, ensure_ascii=False)
        return json.dumps(payload, ensure_ascii=False)

    def _log_request(
        self,
        *,
        action: str,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.debug_logging and path != "/v1/videos/omni-video":
            return
        logger.info(
            "Kling request | action=%s | method=%s | path=%s\npayload=%s\nparams=%s",
            action,
            method,
            path,
            self._json_for_log(payload or {}),
            self._json_for_log(params or {}),
        )

    def _log_response(self, *, action: str, payload: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info("Kling response | action=%s\n%s", action, self._json_for_log(payload))

    def _unwrap_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if "data" not in payload:
            return payload

        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return {"items": data}

    def _extract_error_message(self, payload: Dict[str, Any]) -> str:
        return str(
            payload.get("task_status_msg")
            or payload.get("error_message")
            or payload.get("message")
            or payload.get("msg")
            or ""
        ).strip()

    def _raise_for_error_payload(self, payload: Dict[str, Any], *, action: str) -> None:
        code = payload.get("code")
        if code in {None, 0, "0", 200, "200"}:
            return
        message = self._extract_error_message(payload) or f"Kling action {action} failed"
        raise RuntimeError(message)

    def _clean_mapping(self, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, item in (value or {}).items():
            if item is None:
                continue
            if isinstance(item, str) and not item.strip():
                continue
            cleaned[key] = item
        return cleaned

    async def _request(
        self,
        *,
        method: str,
        path: str,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cleaned_payload = self._clean_mapping(payload)
        cleaned_params = self._clean_mapping(params)
        self._log_request(
            action=action,
            method=method,
            path=path,
            payload=cleaned_payload,
            params=cleaned_params,
        )

        response = await self.client.request(
            method,
            f"{self.base_url}{path}",
            json=cleaned_payload or None,
            params=cleaned_params or None,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._extract_http_error_detail(response)
            if detail:
                raise httpx.HTTPStatusError(
                    f"{exc}. Response detail: {detail}",
                    request=exc.request,
                    response=exc.response,
                ) from exc
            raise
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            data = {"data": data}

        self._log_response(action=action, payload=data)
        self._raise_for_error_payload(data, action=action)
        return data

    async def _request_with_fallbacks(
        self,
        *,
        attempts: Iterable[Dict[str, Any]],
        action: str,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        materialized_attempts = list(attempts)
        for index, attempt in enumerate(materialized_attempts):
            try:
                return await self._request(
                    method=str(attempt.get("method") or "GET"),
                    path=str(attempt["path"]),
                    action=action,
                    payload=attempt.get("payload"),
                    params=attempt.get("params"),
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                response = exc.response
                if index < len(materialized_attempts) - 1 and response is not None and response.status_code in {400, 404, 405, 422}:
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Kling action {action} failed without a usable fallback")

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

    def _extract_task_response(self, payload: Dict[str, Any]) -> KlingVideoGenerationResponse:
        data = self._unwrap_payload(payload)
        task_id = str(data.get("task_id") or data.get("id") or "").strip()
        if not task_id:
            raise RuntimeError(f"可灵返回中缺少 task_id: {payload}")

        return KlingVideoGenerationResponse(
            task_id=task_id,
            status=str(data.get("task_status") or data.get("status") or "submitted"),
            video_url=self._extract_video_url(data),
            cover_url=self._extract_cover_url(data),
            error_message=self._extract_error_message(data),
            created_at=datetime.now(),
            raw_payload=data,
        )

    def _extract_task_status(self, payload: Dict[str, Any], *, task_id: str) -> KlingVideoTaskStatus:
        data = self._unwrap_payload(payload)
        return KlingVideoTaskStatus(
            task_id=str(data.get("task_id") or task_id),
            status=str(data.get("task_status") or data.get("status") or ""),
            video_url=self._extract_video_url(data),
            cover_url=self._extract_cover_url(data),
            error_message=self._extract_error_message(data),
            raw_payload=data,
        )

    def _normalize_enum_value(
        self,
        value: Any,
        *,
        allowed_values: set[str],
        default: str,
        field_name: str,
    ) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return default
        if normalized in allowed_values:
            return normalized
        raise ValueError(f"{field_name} 不支持当前取值: {normalized}")

    def _normalize_positive_int(self, value: Any, *, field_name: str, default: int) -> int:
        normalized = str(value or "").strip()
        if not normalized:
            return default
        try:
            parsed = int(normalized)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} 必须为整数: {value}") from exc
        if parsed <= 0:
            raise ValueError(f"{field_name} 必须大于 0")
        return parsed

    def _distribute_multi_prompt_durations(self, *, total_duration: int, prompt_count: int) -> List[int]:
        if prompt_count <= 0:
            return []
        if prompt_count > total_duration:
            raise ValueError("multi_prompt 数量不能超过总时长，否则无法保证每个分镜时长至少为 1 秒")
        base_duration = total_duration // prompt_count
        remainder = total_duration % prompt_count
        return [base_duration + (1 if index < remainder else 0) for index in range(prompt_count)]

    def _normalize_omni_multi_prompt(self, raw_value: Any, *, total_duration: int) -> List[Dict[str, Any]]:
        if not isinstance(raw_value, list):
            return []
        if not raw_value:
            return []
        if len(raw_value) > 6:
            raise ValueError("multi_prompt 最多支持 6 个分镜")

        default_durations = self._distribute_multi_prompt_durations(
            total_duration=total_duration,
            prompt_count=len(raw_value),
        )
        normalized_items: List[Dict[str, Any]] = []
        for index, item in enumerate(raw_value, start=1):
            prompt = ""
            prompt_index = index
            prompt_duration = default_durations[index - 1]
            if isinstance(item, dict):
                prompt = str(item.get("prompt") or "").strip()
                if item.get("index") is not None and str(item.get("index")).strip():
                    prompt_index = self._normalize_positive_int(item.get("index"), field_name="multi_prompt.index", default=index)
                if item.get("duration") is not None and str(item.get("duration")).strip():
                    prompt_duration = self._normalize_positive_int(
                        item.get("duration"),
                        field_name="multi_prompt.duration",
                        default=prompt_duration,
                    )
            else:
                prompt = str(item or "").strip()

            if not prompt:
                raise ValueError("multi_prompt 中的 prompt 不能为空")
            if len(prompt) > 512:
                raise ValueError("multi_prompt 中单个分镜 prompt 不能超过 512 个字符")

            normalized_items.append(
                {
                    "index": prompt_index,
                    "prompt": prompt,
                    "duration": str(prompt_duration),
                }
            )

        total_multi_duration = sum(int(item["duration"]) for item in normalized_items)
        if total_multi_duration != total_duration:
            raise ValueError("multi_prompt 所有分镜时长之和必须等于当前任务总时长")
        return normalized_items

    def _normalize_omni_image_list(
        self,
        *,
        image: str,
        image_type: str,
        raw_value: Any,
    ) -> List[Dict[str, str]]:
        source_items = raw_value if isinstance(raw_value, list) else []
        if not source_items and str(image or "").strip():
            source_items = [{"image_url": image, "type": image_type}]

        normalized_items: List[Dict[str, str]] = []
        for item in source_items:
            if not isinstance(item, dict):
                continue
            image_url = str(item.get("image_url") or "").strip()
            if not image_url:
                raise ValueError("image_list.image_url 不能为空")
            normalized_item: Dict[str, str] = {"image_url": image_url}
            frame_type = str(item.get("type") or "").strip()
            if frame_type:
                if frame_type not in SUPPORTED_KLING_IMAGE_REFERENCE_TYPES:
                    raise ValueError(f"image_list.type 不支持当前取值: {frame_type}")
                normalized_item["type"] = frame_type
            normalized_items.append(normalized_item)
        return normalized_items

    def _normalize_omni_element_list(self, raw_value: Any) -> List[Dict[str, int]]:
        if not isinstance(raw_value, list):
            return []
        normalized_items: List[Dict[str, int]] = []
        for item in raw_value:
            if not isinstance(item, dict):
                continue
            raw_element_id = item.get("element_id")
            if raw_element_id is None or not str(raw_element_id).strip():
                raise ValueError("element_list.element_id 不能为空")
            try:
                element_id = int(str(raw_element_id).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"element_list.element_id 必须为整数: {raw_element_id}") from exc
            normalized_items.append({"element_id": element_id})
        return normalized_items

    def _normalize_omni_video_list(self, raw_value: Any) -> List[Dict[str, str]]:
        if not isinstance(raw_value, list):
            return []
        normalized_items: List[Dict[str, str]] = []
        for item in raw_value:
            if not isinstance(item, dict):
                continue
            video_url = str(item.get("video_url") or "").strip()
            if not video_url:
                raise ValueError("video_list.video_url 不能为空")
            refer_type = self._normalize_enum_value(
                item.get("refer_type"),
                allowed_values=SUPPORTED_KLING_VIDEO_REFER_TYPES,
                default="base",
                field_name="video_list.refer_type",
            )
            keep_original_sound = self._normalize_enum_value(
                item.get("keep_original_sound"),
                allowed_values=SUPPORTED_KLING_KEEP_ORIGINAL_SOUND,
                default="no",
                field_name="video_list.keep_original_sound",
            )
            normalized_items.append(
                {
                    "video_url": video_url,
                    "refer_type": refer_type,
                    "keep_original_sound": keep_original_sound,
                }
            )
        if len(normalized_items) > 1:
            raise ValueError("video_list 至多支持 1 段参考视频")
        return normalized_items

    def _normalize_watermark_info(self, raw_value: Any) -> Optional[Dict[str, bool]]:
        if raw_value is None:
            return None
        if not isinstance(raw_value, dict):
            raise ValueError("watermark_info 必须为对象")
        if "enabled" not in raw_value:
            raise ValueError("watermark_info.enabled 不能为空")
        return {"enabled": bool(raw_value.get("enabled"))}

    def _build_omni_payload(
        self,
        *,
        prompt: str,
        image: str = "",
        negative_prompt: str = "",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        callback_url: str = "",
        external_task_id: str = "",
        extra_body: Optional[Dict[str, Any]] = None,
        image_type: str = "first_frame",
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        cleaned_extra_body = self._clean_mapping(extra_body)
        resolved_model_name = self._normalize_model_name(model_name or cleaned_extra_body.get("model_name") or self.model)
        resolved_mode = self._normalize_enum_value(
            cleaned_extra_body.get("mode"),
            allowed_values=SUPPORTED_KLING_VIDEO_MODES,
            default=self.mode,
            field_name="mode",
        )
        normalized_prompt = str(prompt or "").strip()
        normalized_aspect_ratio = str(aspect_ratio or "").strip()
        normalized_duration = self._normalize_positive_int(duration, field_name="duration", default=5)

        explicit_multi_shot = cleaned_extra_body.get("multi_shot")
        if isinstance(explicit_multi_shot, bool):
            multi_shot = explicit_multi_shot
        else:
            multi_shot = bool(cleaned_extra_body.get("shot_type") or cleaned_extra_body.get("multi_prompt"))

        raw_multi_prompt = cleaned_extra_body.get("multi_prompt")
        shot_type_default = "customize" if isinstance(raw_multi_prompt, list) and raw_multi_prompt else ""
        shot_type = ""
        if multi_shot:
            shot_type = self._normalize_enum_value(
                cleaned_extra_body.get("shot_type"),
                allowed_values=SUPPORTED_KLING_MULTI_SHOT_TYPES,
                default=shot_type_default,
                field_name="shot_type",
            )
            if not shot_type:
                raise ValueError("multi_shot=true 时，shot_type 必填")
        normalized_multi_prompt = (
            self._normalize_omni_multi_prompt(raw_multi_prompt, total_duration=normalized_duration)
            if multi_shot and shot_type == "customize"
            else []
        )
        if multi_shot and shot_type == "customize" and not normalized_multi_prompt:
            raise ValueError("multi_shot=true 且 shot_type=customize 时，multi_prompt 不能为空")

        normalized_image_list = self._normalize_omni_image_list(
            image=image,
            image_type=image_type,
            raw_value=cleaned_extra_body.get("image_list"),
        )
        if multi_shot:
            normalized_image_list = [{"image_url": str(item.get("image_url") or "").strip()} for item in normalized_image_list]
        normalized_element_list = self._normalize_omni_element_list(cleaned_extra_body.get("element_list"))
        normalized_video_list = self._normalize_omni_video_list(cleaned_extra_body.get("video_list"))
        normalized_watermark_info = self._normalize_watermark_info(cleaned_extra_body.get("watermark_info"))

        has_first_frame = any(item.get("type") == "first_frame" for item in normalized_image_list)
        has_end_frame = any(item.get("type") == "end_frame" for item in normalized_image_list)
        has_base_video = any(item.get("refer_type") == "base" for item in normalized_video_list)

        if has_end_frame and not has_first_frame:
            raise ValueError("暂不支持仅尾帧，设置 end_frame 时必须同时提供 first_frame")
        if has_base_video and (has_first_frame or has_end_frame):
            raise ValueError("待编辑视频模式下不能同时设置首尾帧")
        if has_base_video and normalized_video_list:
            normalized_aspect_ratio = normalized_aspect_ratio or ""

        if resolved_model_name == "kling-video-o1" and has_end_frame and len(normalized_image_list) > 2:
            raise ValueError("kling-video-o1 在图片超过 2 张时不支持设置尾帧")
        if has_first_frame or has_end_frame:
            if len(normalized_element_list) > 3:
                raise ValueError("使用首帧或首尾帧生视频时，element_list 最多支持 3 个主体")
            if has_end_frame and resolved_model_name == "kling-video-o1" and normalized_element_list:
                raise ValueError("kling-video-o1 使用首尾帧生成视频时不支持主体")

        if normalized_video_list:
            if len(normalized_image_list) + len(normalized_element_list) > 4:
                raise ValueError("有参考视频时，参考图片和参考主体总数不得超过 4")
        elif len(normalized_image_list) + len(normalized_element_list) > 7:
            raise ValueError("无参考视频时，参考图片和参考主体总数不得超过 7")

        raw_sound = cleaned_extra_body.get("sound")
        generate_audio = cleaned_extra_body.get("generate_audio")
        if isinstance(raw_sound, str) and raw_sound.strip():
            sound = self._normalize_enum_value(
                raw_sound,
                allowed_values=SUPPORTED_KLING_SOUND_OPTIONS,
                default="off",
                field_name="sound",
            )
        elif isinstance(generate_audio, bool):
            sound = "on" if generate_audio else "off"
        else:
            sound = "off"
        if normalized_video_list and sound != "off":
            raise ValueError("有参考视频时，sound 只能为 off")

        payload: Dict[str, Any] = {
            "model_name": resolved_model_name,
            "mode": resolved_mode,
            "multi_shot": multi_shot,
            "sound": sound,
        }
        if multi_shot:
            payload["shot_type"] = shot_type
            if shot_type == "customize":
                payload["multi_prompt"] = normalized_multi_prompt
            elif normalized_prompt:
                payload["prompt"] = normalized_prompt
        else:
            if not normalized_prompt:
                raise ValueError("multi_shot=false 时，prompt 不能为空")
            payload["prompt"] = normalized_prompt

        if normalized_image_list:
            payload["image_list"] = normalized_image_list
        if normalized_element_list:
            payload["element_list"] = normalized_element_list
        if normalized_video_list:
            payload["video_list"] = normalized_video_list
        if normalized_watermark_info is not None:
            payload["watermark_info"] = normalized_watermark_info
        if not has_base_video:
            payload["duration"] = str(normalized_duration)
        if normalized_aspect_ratio:
            if normalized_aspect_ratio not in SUPPORTED_KLING_ASPECT_RATIOS:
                raise ValueError(f"aspect_ratio 不支持当前取值: {normalized_aspect_ratio}")
            payload["aspect_ratio"] = normalized_aspect_ratio
        elif not has_first_frame and not has_base_video:
            raise ValueError("未使用首帧参考或视频编辑功能时，aspect_ratio 不能为空")
        if callback_url:
            payload["callback_url"] = callback_url
        if external_task_id:
            payload["external_task_id"] = external_task_id
        passthrough_keys = {
            "model_name",
            "mode",
            "multi_shot",
            "shot_type",
            "multi_prompt",
            "image_list",
            "element_list",
            "video_list",
            "sound",
            "generate_audio",
            "watermark_info",
        }
        for key, value in cleaned_extra_body.items():
            if key in passthrough_keys:
                continue
            payload[key] = value
        return payload

    async def create_omni_video_task(
        self,
        *,
        prompt: str = "",
        image: str = "",
        negative_prompt: str = "",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        callback_url: str = "",
        external_task_id: str = "",
        extra_body: Optional[Dict[str, Any]] = None,
        image_type: str = "first_frame",
        model_name: Optional[str] = None,
    ) -> KlingVideoGenerationResponse:
        data = await self._request(
            method="POST",
            path="/v1/videos/omni-video",
            action="create_omni_video_task",
            payload=self._build_omni_payload(
                prompt=prompt,
                image=image,
                negative_prompt=negative_prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                callback_url=callback_url,
                external_task_id=external_task_id,
                extra_body=extra_body,
                image_type=image_type,
                model_name=model_name,
            ),
        )
        return self._extract_task_response(data)

    async def get_video_task_status(
        self,
        *,
        task_id: str,
        task_type: str = VIDEO_TASK_OMNI_GENERATION,
    ) -> KlingVideoTaskStatus:
        data = await self._request(
            method="GET",
            path=f"/v1/videos/omni-video/{task_id}",
            action="get_video_task_status",
        )
        return self._extract_task_status(data, task_id=task_id)

    async def wait_for_completion(
        self,
        task_id: str,
        *,
        task_type: str = VIDEO_TASK_OMNI_GENERATION,
        poll_interval: int = 5,
        max_wait_time: int = 900,
    ) -> KlingVideoGenerationResponse:
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            status = await self.get_video_task_status(task_id=task_id, task_type=task_type)
            logger.info("Kling task status | task_id=%s | task_type=%s | status=%s", task_id, task_type, status.status)

            normalized = status.status.lower()
            if normalized in SUCCESS_VIDEO_TASK_STATUSES:
                return KlingVideoGenerationResponse(
                    task_id=task_id,
                    status="completed",
                    video_url=status.video_url,
                    cover_url=status.cover_url,
                    error_message=status.error_message,
                    completed_at=datetime.now(),
                    raw_payload=status.raw_payload,
                )
            if normalized in FAILED_VIDEO_TASK_STATUSES:
                return KlingVideoGenerationResponse(
                    task_id=task_id,
                    status="failed",
                    error_message=status.error_message or "Kling task failed",
                    raw_payload=status.raw_payload,
                )
            await asyncio.sleep(poll_interval)

        return KlingVideoGenerationResponse(
            task_id=task_id,
            status="timeout",
            error_message="等待可灵视频生成超时",
        )

    async def create_custom_subject(self, *, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="POST",
                path="/v1/general/custom-elements",
                action="create_custom_subject",
                payload=payload,
            )
        )

    async def get_custom_subject(self, element_id: str) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="GET",
                path=f"/v1/general/custom-elements/{element_id}",
                action="get_custom_subject",
            )
        )

    async def list_custom_subjects(self, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="GET",
                path="/v1/general/custom-elements",
                action="list_custom_subjects",
                params=params,
            )
        )

    async def delete_custom_subject(self, element_id: str) -> Dict[str, Any]:
        attempts = [
            {
                "method": "POST",
                "path": "/v1/general/delete-elements",
                "payload": {"element_ids": [element_id]},
            },
            {
                "method": "POST",
                "path": "/v1/general/delete-elements",
                "payload": {"element_id": element_id},
            },
            {
                "method": "DELETE",
                "path": f"/v1/general/custom-elements/{element_id}",
            },
        ]
        return self._unwrap_payload(await self._request_with_fallbacks(attempts=attempts, action="delete_custom_subject"))

    async def create_custom_voice(self, *, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="POST",
                path="/v1/general/custom-voices",
                action="create_custom_voice",
                payload=payload,
            )
        )

    async def get_custom_voice(self, voice_id: str) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="GET",
                path=f"/v1/general/custom-voices/{voice_id}",
                action="get_custom_voice",
            )
        )

    async def list_custom_voices(self, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="GET",
                path="/v1/general/custom-voices",
                action="list_custom_voices",
                params=params,
            )
        )

    async def list_official_voices(self, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._unwrap_payload(
            await self._request(
                method="GET",
                path="/v1/general/presets-voices",
                action="list_official_voices",
                params=params,
            )
        )

    async def delete_custom_voice(self, voice_id: str) -> Dict[str, Any]:
        attempts = [
            {
                "method": "POST",
                "path": "/v1/general/delete-voices",
                "payload": {"voice_ids": [voice_id]},
            },
            {
                "method": "POST",
                "path": "/v1/general/delete-voices",
                "payload": {"voice_id": voice_id},
            },
            {
                "method": "DELETE",
                "path": f"/v1/general/custom-voices/{voice_id}",
            },
        ]
        return self._unwrap_payload(await self._request_with_fallbacks(attempts=attempts, action="delete_custom_voice"))

    async def close(self) -> None:
        await self.client.aclose()


class KlingVideoGenerator(KlingAPIClient):
    """Backward-compatible alias for older pipeline code."""
