#!/usr/bin/env python3
"""Kling API passthrough endpoints."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.core.provider_keys import KLING_API_KEY_ERROR_CODE, MissingProviderConfigError
from app.services.auth_service import get_current_user
from app.services.kling_video import (
    VIDEO_TASK_OMNI_GENERATION,
    KlingAPIClient,
)

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)


class KlingOmniMultiPromptItem(BaseModel):
    index: int = Field(..., ge=1)
    prompt: str = Field(..., min_length=1, max_length=512)
    duration: Union[int, str] = Field(..., description="分镜时长，单位秒")


class KlingOmniImageItem(BaseModel):
    image_url: str = Field(..., min_length=1)
    type: Optional[Literal["first_frame", "end_frame"]] = None


class KlingOmniElementItem(BaseModel):
    element_id: int = Field(..., gt=0)


class KlingOmniVideoItem(BaseModel):
    video_url: str = Field(..., min_length=1)
    refer_type: Literal["feature", "base"] = "base"
    keep_original_sound: Literal["yes", "no"] = "no"


class KlingOmniWatermarkInfo(BaseModel):
    enabled: bool


class KlingOmniVideoRequest(BaseModel):
    model_name: Optional[Literal["kling-video-o1", "kling-v3-omni"]] = Field(
        default=None,
        description="官方默认 kling-video-o1；当前服务未显式传值时沿用服务端配置默认模型",
    )
    multi_shot: bool = False
    shot_type: Optional[Literal["customize", "intelligence"]] = None
    prompt: str = Field(default="", max_length=2500)
    multi_prompt: list[KlingOmniMultiPromptItem] = Field(default_factory=list)
    image_list: list[KlingOmniImageItem] = Field(default_factory=list)
    element_list: list[KlingOmniElementItem] = Field(default_factory=list)
    video_list: list[KlingOmniVideoItem] = Field(default_factory=list)
    sound: Optional[Literal["on", "off"]] = Field(default=None)
    mode: Optional[Literal["std", "pro"]] = Field(default=None)
    aspect_ratio: Optional[Literal["16:9", "9:16", "1:1"]] = None
    duration: Union[int, str] = Field(default=5)
    watermark_info: Optional[KlingOmniWatermarkInfo] = None
    callback_url: Optional[str] = None
    external_task_id: Optional[str] = None
    extra_body: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_official_shape(self) -> "KlingOmniVideoRequest":
        if self.multi_shot and not self.shot_type:
            raise ValueError("multi_shot=true 时，shot_type 必填")
        if self.multi_shot and self.shot_type == "customize" and not self.multi_prompt:
            raise ValueError("multi_shot=true 且 shot_type=customize 时，multi_prompt 不能为空")
        if (not self.multi_shot or self.shot_type == "intelligence") and not self.prompt.strip():
            raise ValueError("当前配置下 prompt 不能为空")
        return self


class KlingCreateCustomSubjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    image: str = Field(..., min_length=1)
    extra_body: Dict[str, Any] = Field(default_factory=dict)


class KlingCreateCustomVoiceRequest(BaseModel):
    name: Optional[str] = None
    voice_name: Optional[str] = None
    audio_file: Optional[str] = None
    text: Optional[str] = None
    prompt_text: Optional[str] = None
    extra_body: Dict[str, Any] = Field(default_factory=dict)


def _raise_provider_config_http_exception(exc: MissingProviderConfigError) -> None:
    raise HTTPException(
        status_code=428,
        detail=str(exc),
        headers={"X-Error-Code": exc.code or KLING_API_KEY_ERROR_CODE},
    ) from exc


def _extract_http_error_detail(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    if response is None:
        return str(exc)
    try:
        payload = response.json()
    except Exception:
        text = response.text.strip()
        return text or str(exc)
    if isinstance(payload, dict):
        detail = str(payload.get("message") or payload.get("msg") or payload)
    else:
        detail = json.dumps(payload, ensure_ascii=False)

    normalized = detail.strip()
    lowered = normalized.lower()
    if "account balance not enough" in lowered:
        return "可灵账户余额不足，请先充值后再创建主体或生成视频。"
    return normalized


def _build_query_params(**kwargs: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        params[key] = value
    return params


def _asset_reference_to_path(image_reference: str) -> Optional[Path]:
    normalized = str(image_reference or "").strip()
    if not normalized:
        return None

    if normalized.startswith("/uploads/"):
        relative_path = normalized.replace("/uploads/", "", 1)
        return Path(settings.UPLOAD_DIR) / relative_path

    if normalized.startswith("http://") or normalized.startswith("https://"):
        parsed = urlsplit(normalized)
        if parsed.path.startswith("/uploads/"):
            relative_path = parsed.path.replace("/uploads/", "", 1)
            return Path(settings.UPLOAD_DIR) / relative_path
        return None

    candidate = Path(normalized).expanduser()
    if candidate.exists():
        return candidate
    return None


def _normalize_subject_image_payload(image_reference: str) -> str:
    normalized = str(image_reference or "").strip()
    if not normalized:
        return normalized

    if normalized.startswith("data:"):
        _, _, encoded = normalized.partition(",")
        return encoded.strip()

    asset_path = _asset_reference_to_path(normalized)
    if asset_path and asset_path.exists():
        return base64.b64encode(asset_path.read_bytes()).decode("utf-8")

    return normalized


def _normalize_subject_refer_list(raw_value: Any) -> list[Dict[str, str]]:
    if not isinstance(raw_value, list):
        return []

    normalized_items: list[Dict[str, str]] = []
    for item in raw_value:
        image_reference = ""
        if isinstance(item, dict):
            image_reference = str(item.get("image_url") or item.get("url") or item.get("image") or "").strip()
        elif isinstance(item, str):
            image_reference = item.strip()
        if not image_reference:
            continue
        normalized_payload = _normalize_subject_image_payload(image_reference)
        if not normalized_payload:
            continue
        normalized_items.append({"image_url": normalized_payload})
        if len(normalized_items) >= 3:
            break
    return normalized_items


def _summarize_binary_reference(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "<empty>"
    if normalized.startswith("data:"):
        return f"<data-url length={len(normalized)}>"
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    if normalized.startswith("/uploads/"):
        return normalized
    if len(normalized) > 120:
        return f"<raw-base64 length={len(normalized)}>"
    return normalized


async def _with_kling_client(
    callback: Callable[[KlingAPIClient], Awaitable[Dict[str, Any]]],
    *,
    action_label: str = "kling_request",
) -> Dict[str, Any]:
    try:
        client = KlingAPIClient()
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)

    try:
        return await callback(client)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        detail = _extract_http_error_detail(exc)
        logger.warning("Kling request failed | action=%s | status=%s | detail=%s", action_label, status_code, detail)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        logger.exception("Kling request raised unexpected error | action=%s", action_label)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()


def _build_omni_extra_body(request: KlingOmniVideoRequest) -> Dict[str, Any]:
    extra_body = dict(request.extra_body or {})
    if request.model_name:
        extra_body["model_name"] = request.model_name
    extra_body["multi_shot"] = request.multi_shot
    if request.shot_type:
        extra_body["shot_type"] = request.shot_type
    if request.multi_prompt:
        extra_body["multi_prompt"] = [item.model_dump(exclude_none=True) for item in request.multi_prompt]
    if request.image_list:
        extra_body["image_list"] = [item.model_dump(exclude_none=True) for item in request.image_list]
    if request.element_list:
        extra_body["element_list"] = [item.model_dump(exclude_none=True) for item in request.element_list]
    if request.video_list:
        extra_body["video_list"] = [item.model_dump(exclude_none=True) for item in request.video_list]
    if request.sound:
        extra_body["sound"] = request.sound
    if request.mode:
        extra_body["mode"] = request.mode
    if request.watermark_info is not None:
        extra_body["watermark_info"] = request.watermark_info.model_dump(exclude_none=True)
    return extra_body


def _serialize_generation_response(response: Any) -> Dict[str, Any]:
    return {
        "task_id": response.task_id,
        "status": response.status,
        "video_url": response.video_url,
        "cover_url": response.cover_url,
        "error_message": response.error_message,
        "raw_payload": response.raw_payload,
    }


def _serialize_task_status(status: Any) -> Dict[str, Any]:
    return {
        "task_id": status.task_id,
        "status": status.status,
        "video_url": status.video_url,
        "cover_url": status.cover_url,
        "error_message": status.error_message,
        "raw_payload": status.raw_payload,
    }


@router.post("/videos/omni-video")
async def create_omni_video(request: KlingOmniVideoRequest) -> Dict[str, Any]:
    extra_body = _build_omni_extra_body(request)

    async def _execute(client: KlingAPIClient) -> Dict[str, Any]:
        response = await client.create_omni_video_task(
            prompt=request.prompt,
            duration=int(request.duration),
            aspect_ratio=str(request.aspect_ratio or ""),
            callback_url=str(request.callback_url or ""),
            external_task_id=str(request.external_task_id or ""),
            extra_body=extra_body,
            model_name=request.model_name,
        )
        return _serialize_generation_response(response)

    return await _with_kling_client(_execute, action_label="create_omni_video")


@router.get("/videos/omni-video/{id}")
async def get_omni_video(id: str) -> Dict[str, Any]:
    async def _execute(client: KlingAPIClient) -> Dict[str, Any]:
        status = await client.get_video_task_status(task_id=id, task_type=VIDEO_TASK_OMNI_GENERATION)
        return _serialize_task_status(status)

    return await _with_kling_client(_execute)


@router.post("/subjects")
async def create_custom_subject(request: KlingCreateCustomSubjectRequest) -> Dict[str, Any]:
    payload = request.extra_body.copy()
    element_name = str(payload.get("element_name") or payload.get("name") or request.name).strip()
    element_description = str(
        payload.get("element_description") or payload.get("description") or payload.get("summary") or element_name
    ).strip()
    element_image = _normalize_subject_image_payload(
        str(payload.get("element_frontal_image") or payload.get("image") or request.image)
    )
    element_refer_list = _normalize_subject_refer_list(
        payload.get("element_refer_list") or payload.get("refer_images") or payload.get("images") or []
    )
    payload.pop("name", None)
    payload.pop("image", None)
    payload.pop("description", None)
    payload.pop("summary", None)
    payload.pop("refer_images", None)
    payload.pop("images", None)
    payload.setdefault("element_name", element_name)
    payload.setdefault("element_description", element_description)
    payload["element_frontal_image"] = element_image
    payload["element_refer_list"] = element_refer_list

    logger.info(
        "Kling create subject request | name=%s | description_length=%s | frontal=%s | refer_count=%s | refer_images=%s",
        payload.get("element_name"),
        len(str(payload.get("element_description") or "")),
        _summarize_binary_reference(str(payload.get("element_frontal_image") or "")),
        len(element_refer_list),
        [_summarize_binary_reference(str(item.get("image_url") or "")) for item in element_refer_list],
    )

    async def _execute(client: KlingAPIClient) -> Dict[str, Any]:
        response = await client.create_custom_subject(payload=payload)
        logger.info(
            "Kling create subject response | element_id=%s | element_name=%s | status=%s",
            response.get("element_id"),
            response.get("element_name") or response.get("name"),
            response.get("status") or response.get("task_status") or response.get("element_status"),
        )
        return response

    return await _with_kling_client(_execute, action_label="create_custom_subject")


@router.get("/subjects/{subject_id}")
async def get_custom_subject(subject_id: str) -> Dict[str, Any]:
    return await _with_kling_client(lambda client: client.get_custom_subject(subject_id))


@router.get("/subjects")
async def list_custom_subjects(
    page_num: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=100),
    name: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    params = _build_query_params(page_num=page_num, page_size=page_size, name=name, status=status)
    return await _with_kling_client(lambda client: client.list_custom_subjects(params=params))


@router.delete("/subjects/{subject_id}")
async def delete_custom_subject(subject_id: str) -> Dict[str, Any]:
    return await _with_kling_client(lambda client: client.delete_custom_subject(subject_id))


@router.get("/voices/presets")
async def list_official_voices(
    page_num: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=100),
    language: Optional[str] = None,
) -> Dict[str, Any]:
    params = _build_query_params(page_num=page_num, page_size=page_size, language=language)
    return await _with_kling_client(lambda client: client.list_official_voices(params=params))


@router.post("/voices")
async def create_custom_voice(request: KlingCreateCustomVoiceRequest) -> Dict[str, Any]:
    payload = request.extra_body.copy()
    if request.name:
        payload.setdefault("name", request.name)
    if request.voice_name:
        payload.setdefault("voice_name", request.voice_name)
    if request.audio_file:
        payload.setdefault("audio_file", request.audio_file)
    if request.text:
        payload.setdefault("text", request.text)
    if request.prompt_text:
        payload.setdefault("prompt_text", request.prompt_text)
    if not payload:
        raise HTTPException(status_code=400, detail="创建自定义音色至少需要提供一个有效字段。")
    return await _with_kling_client(lambda client: client.create_custom_voice(payload=payload))


@router.get("/voices")
async def list_custom_voices(
    page_num: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=100),
    name: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    params = _build_query_params(page_num=page_num, page_size=page_size, name=name, status=status)
    return await _with_kling_client(lambda client: client.list_custom_voices(params=params))


@router.get("/voices/{voice_id}")
async def get_custom_voice(voice_id: str) -> Dict[str, Any]:
    return await _with_kling_client(lambda client: client.get_custom_voice(voice_id))


@router.delete("/voices/{voice_id}")
async def delete_custom_voice(voice_id: str) -> Dict[str, Any]:
    return await _with_kling_client(lambda client: client.delete_custom_voice(voice_id))
