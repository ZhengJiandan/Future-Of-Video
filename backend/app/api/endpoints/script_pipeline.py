#!/usr/bin/env python3
"""
剧本主链路 API。

当前只保留单条端到端工作流：
1. upload-reference: 上传用户参考图
2. generate-script: 生成完整剧本
3. split-script: 审核剧本后拆分片段
4. generate-keyframes: 生成并审核片段首尾帧
5. render: 审核首尾帧后发起视频生成与合成
6. render/{task_id}: 查询异步渲染状态
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Union

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.provider_keys import (
    DOUBAO_API_KEY_ERROR_CODE,
    KLING_API_KEY_ERROR_CODE,
    MissingProviderConfigError,
    get_effective_doubao_api_key,
    kling_credentials_configured,
)
from app.db import get_db
from app.services.auth_service import get_current_user
from app.services.pipeline_character_library import pipeline_character_library_service
from app.services.pipeline_project_service import pipeline_project_service
from app.services.pipeline_scene_library import pipeline_scene_library_service
from app.services.pipeline_workflow import pipeline_workflow_service
from app.services.profile_image_analyzer import profile_image_analyzer_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _raise_provider_config_http_exception(exc: MissingProviderConfigError) -> None:
    raise HTTPException(
        status_code=428,
        detail=str(exc),
        headers={"X-Error-Code": exc.code},
    ) from exc


def _normalize_optional_duration(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _split_request_matches_state(
    state: Dict[str, Any],
    *,
    script_text: str,
    max_segment_duration: float,
    target_total_duration: Optional[float],
) -> bool:
    saved_script = str(state.get("scriptDraft") or "").strip()
    if saved_script != str(script_text or "").strip():
        return False
    saved_max_duration = round(float(state.get("maxSegmentDuration") or 0.0), 2)
    if saved_max_duration != round(float(max_segment_duration), 2):
        return False
    raw_saved_target_duration = state.get("targetTotalDuration")
    try:
        saved_target_duration = _normalize_optional_duration(
            None if raw_saved_target_duration in {None, ""} else float(raw_saved_target_duration)
        )
    except (TypeError, ValueError):
        saved_target_duration = None
    return saved_target_duration == _normalize_optional_duration(target_total_duration)


def _build_split_state_signature(
    *,
    script_text: str,
    max_segment_duration: float,
    target_total_duration: Optional[float],
) -> str:
    payload = (
        f"{str(script_text or '').strip()}|"
        f"{round(float(max_segment_duration), 2)}|"
        f"{_normalize_optional_duration(target_total_duration)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_split_response_from_state(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    segments = state.get("segments")
    if not isinstance(segments, list) or not segments:
        return None

    validation_report = state.get("splitValidationReport") if isinstance(state.get("splitValidationReport"), dict) else None
    total_duration = 0.0
    if validation_report and validation_report.get("actual_total_duration") is not None:
        try:
            total_duration = float(validation_report.get("actual_total_duration") or 0.0)
        except (TypeError, ValueError):
            total_duration = 0.0
    if total_duration <= 0:
        total_duration = round(
            sum(float((segment or {}).get("duration") or 0.0) for segment in segments if isinstance(segment, dict)),
            2,
        )

    return {
        "script_text": str(state.get("scriptDraft") or ""),
        "total_duration": total_duration,
        "segment_count": len(segments),
        "segments": segments,
        "continuity_points": state.get("continuityPoints") if isinstance(state.get("continuityPoints"), list) else [],
        "validation_report": validation_report,
    }


class ReferenceAssetPayload(BaseModel):
    id: str
    url: str
    thumbnail_url: str = ""
    filename: str
    original_filename: str = ""
    content_type: str = "image/png"
    size: int = 0
    source: str = "upload"


class CharacterProfilePayload(BaseModel):
    id: str = ""
    name: str
    category: str = ""
    role: str = ""
    archetype: str = ""
    age_range: str = ""
    gender_presentation: str = ""
    description: str = ""
    appearance: str = ""
    personality: str = ""
    core_appearance: str = ""
    hair: str = ""
    face_features: str = ""
    body_shape: str = ""
    outfit: str = ""
    gear: str = ""
    color_palette: str = ""
    visual_do_not_change: str = ""
    speaking_style: str = ""
    common_actions: str = ""
    emotion_baseline: str = ""
    voice_description: str = ""
    forbidden_behaviors: str = ""
    prompt_hint: str = ""
    llm_summary: str = ""
    image_prompt_base: str = ""
    video_prompt_base: str = ""
    negative_prompt: str = ""
    tags: List[str] = Field(default_factory=list)
    must_keep: List[str] = Field(default_factory=list)
    forbidden_traits: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    profile_version: int = 1
    source: str = "library"
    reference_image_url: str = ""
    reference_image_original_name: str = ""
    three_view_image_url: str = ""
    three_view_prompt: str = ""
    face_closeup_image_url: str = ""
    created_at: str = ""
    updated_at: str = ""


class CreateCharacterRequest(BaseModel):
    name: str = Field(..., min_length=1, description="角色名称")
    category: str = Field(default="", description="角色分类")
    role: str = Field(default="", description="角色定位")
    archetype: str = Field(default="", description="角色原型")
    age_range: str = Field(default="", description="年龄范围")
    gender_presentation: str = Field(default="", description="性别呈现")
    description: str = Field(default="", description="角色设定描述")
    appearance: str = Field(default="", description="外观描述")
    personality: str = Field(default="", description="性格描述")
    core_appearance: str = Field(default="", description="核心外观")
    hair: str = Field(default="", description="发型")
    face_features: str = Field(default="", description="面部特征")
    body_shape: str = Field(default="", description="体态")
    outfit: str = Field(default="", description="服装")
    gear: str = Field(default="", description="装备")
    color_palette: str = Field(default="", description="配色")
    visual_do_not_change: str = Field(default="", description="视觉不可变项")
    speaking_style: str = Field(default="", description="说话方式")
    common_actions: str = Field(default="", description="常见动作")
    emotion_baseline: str = Field(default="", description="情绪基线")
    voice_description: str = Field(default="", description="角色音色描述")
    forbidden_behaviors: str = Field(default="", description="禁止行为")
    prompt_hint: str = Field(default="", description="额外提示词")
    llm_summary: str = Field(default="", description="给剧本模型的压缩档案")
    image_prompt_base: str = Field(default="", description="给图像模型的稳定描述")
    video_prompt_base: str = Field(default="", description="给视频模型的稳定描述")
    negative_prompt: str = Field(default="", description="负面提示词")
    tags: List[str] = Field(default_factory=list, description="标签")
    must_keep: List[str] = Field(default_factory=list, description="必须保持")
    forbidden_traits: List[str] = Field(default_factory=list, description="禁止特征")
    aliases: List[str] = Field(default_factory=list, description="别名")
    profile_version: int = Field(default=1, ge=1, description="档案版本")
    source: str = Field(default="library", description="来源标记")
    reference_image_url: str = Field(default="", description="参考图 URL")
    reference_image_original_name: str = Field(default="", description="参考图原始文件名")
    three_view_image_url: str = Field(default="", description="三视图图片 URL")
    three_view_prompt: str = Field(default="", description="三视图生成提示词")
    face_closeup_image_url: str = Field(default="", description="面部特写图片 URL")
    auto_generate_identity_assets: bool = Field(default=True, description="是否自动生成三视图和面部特写")


class SceneProfilePayload(BaseModel):
    id: str = ""
    name: str
    category: str = ""
    scene_type: str = ""
    description: str = ""
    story_function: str = ""
    location: str = ""
    scene_rules: str = ""
    time_setting: str = ""
    weather: str = ""
    lighting: str = ""
    atmosphere: str = ""
    architecture_style: str = ""
    color_palette: str = ""
    prompt_hint: str = ""
    llm_summary: str = ""
    image_prompt_base: str = ""
    video_prompt_base: str = ""
    negative_prompt: str = ""
    tags: List[str] = Field(default_factory=list)
    allowed_characters: List[str] = Field(default_factory=list)
    props_must_have: List[str] = Field(default_factory=list)
    props_forbidden: List[str] = Field(default_factory=list)
    must_have_elements: List[str] = Field(default_factory=list)
    forbidden_elements: List[str] = Field(default_factory=list)
    camera_preferences: List[str] = Field(default_factory=list)
    profile_version: int = 1
    source: str = "library"
    reference_image_url: str = ""
    reference_image_original_name: str = ""
    created_at: str = ""
    updated_at: str = ""


class CreateSceneRequest(BaseModel):
    name: str = Field(..., min_length=1, description="场景名称")
    category: str = Field(default="", description="场景分类")
    scene_type: str = Field(default="", description="场景类型")
    description: str = Field(default="", description="场景描述")
    story_function: str = Field(default="", description="剧情功能")
    location: str = Field(default="", description="地点")
    scene_rules: str = Field(default="", description="场景规则")
    time_setting: str = Field(default="", description="时间设定")
    weather: str = Field(default="", description="天气")
    lighting: str = Field(default="", description="灯光")
    atmosphere: str = Field(default="", description="氛围")
    architecture_style: str = Field(default="", description="建筑风格")
    color_palette: str = Field(default="", description="场景配色")
    prompt_hint: str = Field(default="", description="补充提示词")
    llm_summary: str = Field(default="", description="给剧本模型的压缩档案")
    image_prompt_base: str = Field(default="", description="给图像模型的稳定描述")
    video_prompt_base: str = Field(default="", description="给视频模型的稳定描述")
    negative_prompt: str = Field(default="", description="负面提示词")
    tags: List[str] = Field(default_factory=list, description="标签")
    allowed_characters: List[str] = Field(default_factory=list, description="允许角色")
    props_must_have: List[str] = Field(default_factory=list, description="必备道具")
    props_forbidden: List[str] = Field(default_factory=list, description="禁用道具")
    must_have_elements: List[str] = Field(default_factory=list, description="必须元素")
    forbidden_elements: List[str] = Field(default_factory=list, description="禁止元素")
    camera_preferences: List[str] = Field(default_factory=list, description="镜头偏好")
    profile_version: int = Field(default=1, ge=1, description="档案版本")
    source: str = Field(default="library", description="来源标记")
    reference_image_url: str = Field(default="", description="参考图 URL")
    reference_image_original_name: str = Field(default="", description="参考图原始文件名")


class GenerateCharacterThreeViewRequest(BaseModel):
    reference_image_url: str = Field(..., min_length=1, description="角色参考图 URL")
    name: str = Field(default="", description="角色名称")
    role: str = Field(default="", description="角色定位")
    description: str = Field(default="", description="角色设定")
    appearance: str = Field(default="", description="外观设定")
    personality: str = Field(default="", description="性格设定")
    prompt_hint: str = Field(default="", description="补充提示词")


class GenerateCharacterPrototypeRequest(BaseModel):
    base_image_url: str = Field(default="", description="当前角色图片 URL，可为空")
    name: str = Field(default="", description="角色名称")
    role: str = Field(default="", description="角色定位")
    description: str = Field(default="", description="角色设定")
    appearance: str = Field(default="", description="外观设定")
    personality: str = Field(default="", description="性格设定")
    prompt_hint: str = Field(default="", description="补充提示词")
    llm_summary: str = Field(default="", description="压缩档案")
    image_prompt_base: str = Field(default="", description="图像稳定描述")
    refine_prompt: str = Field(default="", description="用户微调要求")


class GenerateScenePrototypeRequest(BaseModel):
    base_image_url: str = Field(default="", description="当前场景图片 URL，可为空")
    name: str = Field(default="", description="场景名称")
    scene_type: str = Field(default="", description="场景类型")
    description: str = Field(default="", description="场景描述")
    story_function: str = Field(default="", description="剧情功能")
    location: str = Field(default="", description="地点")
    time_setting: str = Field(default="", description="时间设定")
    weather: str = Field(default="", description="天气")
    lighting: str = Field(default="", description="灯光")
    atmosphere: str = Field(default="", description="氛围")
    architecture_style: str = Field(default="", description="建筑风格")
    color_palette: str = Field(default="", description="配色")
    scene_rules: str = Field(default="", description="场景规则")
    prompt_hint: str = Field(default="", description="补充提示词")
    llm_summary: str = Field(default="", description="压缩档案")
    image_prompt_base: str = Field(default="", description="图像稳定描述")
    refine_prompt: str = Field(default="", description="用户微调要求")


class AnalyzeCharacterImageRequest(BaseModel):
    reference_image_url: str = Field(..., min_length=1, description="角色参考图 URL")
    reference_image_original_name: str = Field(default="", description="角色参考图原始文件名")


class AnalyzeSceneImageRequest(BaseModel):
    reference_image_url: str = Field(..., min_length=1, description="场景参考图 URL")
    reference_image_original_name: str = Field(default="", description="场景参考图原始文件名")


class GenerateScriptRequest(BaseModel):
    """完整剧本生成请求。"""

    project_id: Optional[str] = Field(default=None, description="当前项目 ID，可为空")
    user_input: str = Field(..., min_length=1, description="用户的原始剧情描述")
    style: str = Field(default="", description="视觉风格偏好")
    target_total_duration: Optional[float] = Field(default=None, ge=10.0, le=300.0, description="目标总时长")
    selected_character_ids: List[str] = Field(default_factory=list, description="已选角色档案 ID")
    selected_scene_ids: List[str] = Field(default_factory=list, description="已选场景档案 ID")
    character_profiles: List[CharacterProfilePayload] = Field(default_factory=list, description="直接传入的角色档案")
    scene_profiles: List[SceneProfilePayload] = Field(default_factory=list, description="直接传入的场景档案")
    reference_images: List[ReferenceAssetPayload] = Field(default_factory=list, description="参考图列表")
    generation_intent: Dict[str, Any] = Field(default_factory=dict, description="确认角色阶段已生成的角色意图")
    character_resolution: Dict[str, Any] = Field(default_factory=dict, description="确认角色阶段已生成的角色确认结果")


class PrepareCharactersRequest(BaseModel):
    user_input: str = Field(..., min_length=1, description="用户的原始剧情描述")
    style: str = Field(default="", description="视觉风格偏好")
    target_total_duration: Optional[float] = Field(default=None, ge=10.0, le=300.0, description="目标总时长")
    selected_character_ids: List[str] = Field(default_factory=list, description="已选角色档案 ID")
    character_profiles: List[CharacterProfilePayload] = Field(default_factory=list, description="直接传入的角色档案")


class SplitScriptRequest(BaseModel):
    """剧本拆分请求。"""

    project_id: Optional[str] = Field(default=None, description="当前项目 ID，可为空")
    script_text: str = Field(..., min_length=1, description="用户审核后的完整剧本文本")
    max_segment_duration: float = Field(default=10.0, ge=3.0, le=10.0)
    target_total_duration: Optional[float] = Field(default=None, ge=10.0, le=300.0)


class SegmentDialoguePayload(BaseModel):
    text: str = ""
    speaker_name: str = ""
    speaker_character_id: str = ""
    emotion: str = ""
    tone: str = ""


class SegmentPayload(BaseModel):
    """前端可编辑片段结构。"""

    segment_number: int
    title: str
    description: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = Field(default=5.0, ge=1.0, le=10.0)
    shots_summary: str = ""
    key_actions: List[str] = Field(default_factory=list)
    key_dialogues: List[Union[str, SegmentDialoguePayload]] = Field(default_factory=list)
    transition_in: str = ""
    transition_out: str = ""
    continuity_from_prev: str = ""
    continuity_to_next: str = ""
    video_prompt: str = ""
    negative_prompt: str = ""
    generation_config: Dict[str, Any] = Field(default_factory=dict)
    scene_profile_id: str = ""
    scene_profile_version: int = 1
    character_profile_ids: List[str] = Field(default_factory=list)
    character_profile_versions: Dict[str, int] = Field(default_factory=dict)
    prompt_focus: str = ""
    contains_primary_character: bool = False
    ending_contains_primary_character: bool = False
    pre_generate_start_frame: bool = False
    start_frame_generation_reason: str = ""
    prefer_primary_character_end_frame: bool = False
    new_character_profile_ids: List[str] = Field(default_factory=list)
    late_entry_character_profile_ids: List[str] = Field(default_factory=list)
    handoff_character_profile_ids: List[str] = Field(default_factory=list)
    ending_contains_handoff_characters: bool = False
    prefer_character_handoff_end_frame: bool = False
    video_url: str = ""
    status: str = "ready"


class KeyframeAssetPayload(BaseModel):
    asset_url: str
    asset_type: str
    asset_filename: str
    prompt: str = ""
    source: str = ""
    status: str = "completed"
    notes: str = ""


class KeyframeBundlePayload(BaseModel):
    segment_number: int
    title: str
    start_frame: KeyframeAssetPayload
    end_frame: KeyframeAssetPayload
    continuity_notes: str = ""
    status: str = "ready"


class GenerateKeyframesRequest(BaseModel):
    project_title: str = Field(default="未命名项目")
    style: str = Field(default="", description="视觉风格偏好")
    selected_character_ids: List[str] = Field(default_factory=list, description="已选角色档案 ID")
    selected_scene_ids: List[str] = Field(default_factory=list, description="已选场景档案 ID")
    character_profiles: List[CharacterProfilePayload] = Field(default_factory=list, description="直接传入的角色档案")
    scene_profiles: List[SceneProfilePayload] = Field(default_factory=list, description="直接传入的场景档案")
    reference_images: List[ReferenceAssetPayload] = Field(default_factory=list, description="参考图列表")
    segments: List[SegmentPayload] = Field(..., min_length=1)


async def _resolve_character_profiles(
    db: AsyncSession,
    *,
    selected_character_ids: List[str],
    direct_character_profiles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    selected_profiles = await pipeline_character_library_service.get_profiles_by_ids(db, selected_character_ids)
    return pipeline_character_library_service.merge_profiles(
        selected_profiles=selected_profiles,
        direct_profiles=direct_character_profiles,
    )


async def _resolve_scene_profiles(
    db: AsyncSession,
    *,
    selected_scene_ids: List[str],
    direct_scene_profiles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    selected_profiles = await pipeline_scene_library_service.get_profiles_by_ids(db, selected_scene_ids)
    return pipeline_scene_library_service.merge_profiles(
        selected_profiles=selected_profiles,
        direct_profiles=direct_scene_profiles,
    )


@router.get("/characters")
async def list_characters(db: AsyncSession = Depends(get_db)):
    return {
        "success": True,
        "items": await pipeline_character_library_service.list_profiles(db),
    }


@router.get("/tts/voices")
async def list_tts_voices():
    raise HTTPException(status_code=410, detail="旧版音色目录链路已停用")


@router.get("/characters/{character_id}")
async def get_character(character_id: str, db: AsyncSession = Depends(get_db)):
    profile = await pipeline_character_library_service.get_profile_by_id(db, character_id)
    if not profile:
        raise HTTPException(status_code=404, detail="角色档案不存在")
    return {
        "success": True,
        "item": profile,
    }


@router.post("/characters")
async def create_character(request: CreateCharacterRequest, db: AsyncSession = Depends(get_db)):
    try:
        profile = await pipeline_character_library_service.create_profile(db, request.model_dump())
        return {
            "success": True,
            "message": "角色档案已保存",
            **profile,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Create character failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色档案保存失败，请稍后重试") from exc


@router.put("/characters/{character_id}")
async def update_character(
    character_id: str,
    request: CreateCharacterRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        profile = await pipeline_character_library_service.update_profile(
            db,
            character_id,
            request.model_dump(),
        )
        if not profile:
            raise HTTPException(status_code=404, detail="角色档案不存在")
        return {
            "success": True,
            "message": "角色档案已更新",
            **profile,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Update character failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色档案更新失败，请稍后重试") from exc


@router.post("/characters/upload-reference")
async def upload_character_reference(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        result = await pipeline_character_library_service.save_reference_upload(
            filename=file.filename or "character-reference.png",
            content=content,
            content_type=file.content_type,
        )
        return {
            "success": True,
            "message": "角色参考图上传成功",
            **result,
        }
    except Exception as exc:
        logger.error("Upload character reference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色参考图上传失败，请稍后重试") from exc


@router.post("/characters/generate-three-view")
async def generate_character_three_view(request: GenerateCharacterThreeViewRequest):
    try:
        result = await pipeline_character_library_service.generate_three_view_asset(**request.model_dump())
        return {
            "success": True,
            "message": "角色三视图生成完成",
            **result,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Generate character three view failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色三视图生成失败，请稍后重试") from exc


@router.post("/characters/generate-prototype")
async def generate_character_prototype(request: GenerateCharacterPrototypeRequest):
    try:
        result = await pipeline_character_library_service.generate_character_image_asset(
            **request.model_dump(),
        )
        return {
            "success": True,
            "message": "角色原型图生成完成",
            **result,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Generate character prototype failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色原型图生成失败，请稍后重试") from exc


@router.post("/characters/generate-voice-preview")
async def generate_character_voice_preview():
    raise HTTPException(status_code=410, detail="旧版角色试音链路已停用")


@router.post("/characters/analyze-reference")
async def analyze_character_reference(request: AnalyzeCharacterImageRequest):
    image_path = pipeline_character_library_service._asset_url_to_path(request.reference_image_url)
    if not image_path:
        raise HTTPException(status_code=400, detail="参考图地址无效")
    try:
        fields = await profile_image_analyzer_service.analyze_character_image(
            image_path=image_path,
            filename=request.reference_image_original_name,
        )
        return {
            "success": True,
            "message": "角色图片分析完成",
            "fields": fields,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.error("Analyze character reference failed with upstream status: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="角色图片分析服务暂时不可用，请稍后重试") from exc
    except Exception as exc:
        logger.error("Analyze character reference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色图片分析失败，请稍后重试") from exc


@router.post("/scenes/generate-prototype")
async def generate_scene_prototype(request: GenerateScenePrototypeRequest):
    try:
        result = await pipeline_scene_library_service.generate_scene_image_asset(**request.model_dump())
        return {
            "success": True,
            "message": "场景原型图生成完成",
            **result,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Generate scene prototype failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="场景图片生成失败，请稍后重试") from exc


@router.post("/scenes/analyze-reference")
async def analyze_scene_reference(request: AnalyzeSceneImageRequest):
    image_path = pipeline_scene_library_service._asset_url_to_path(request.reference_image_url)
    if not image_path:
        raise HTTPException(status_code=400, detail="参考图地址无效")
    try:
        fields = await profile_image_analyzer_service.analyze_scene_image(
            image_path=image_path,
            filename=request.reference_image_original_name,
        )
        return {
            "success": True,
            "message": "场景图片分析完成",
            "fields": fields,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.error("Analyze scene reference failed with upstream status: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="场景图片分析服务暂时不可用，请稍后重试") from exc
    except Exception as exc:
        logger.error("Analyze scene reference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="场景图片分析失败，请稍后重试") from exc


@router.get("/scenes")
async def list_scenes(db: AsyncSession = Depends(get_db)):
    return {
        "success": True,
        "items": await pipeline_scene_library_service.list_profiles(db),
    }


@router.get("/scenes/{scene_id}")
async def get_scene(scene_id: str, db: AsyncSession = Depends(get_db)):
    profile = await pipeline_scene_library_service.get_profile_by_id(db, scene_id)
    if not profile:
        raise HTTPException(status_code=404, detail="场景档案不存在")
    return {
        "success": True,
        "item": profile,
    }


@router.post("/scenes")
async def create_scene(request: CreateSceneRequest, db: AsyncSession = Depends(get_db)):
    try:
        profile = await pipeline_scene_library_service.create_profile(db, request.model_dump())
        return {
            "success": True,
            "message": "场景档案已保存",
            **profile,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Create scene failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="场景档案保存失败，请稍后重试") from exc


@router.put("/scenes/{scene_id}")
async def update_scene(
    scene_id: str,
    request: CreateSceneRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        profile = await pipeline_scene_library_service.update_profile(
            db,
            scene_id,
            request.model_dump(),
        )
        if not profile:
            raise HTTPException(status_code=404, detail="场景档案不存在")
        return {
            "success": True,
            "message": "场景档案已更新",
            **profile,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Update scene failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="场景档案更新失败，请稍后重试") from exc


@router.post("/scenes/upload-reference")
async def upload_scene_reference(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        result = await pipeline_scene_library_service.save_reference_upload(
            filename=file.filename or "scene-reference.png",
            content=content,
            content_type=file.content_type,
        )
        return {
            "success": True,
            "message": "场景参考图上传成功",
            **result,
        }
    except Exception as exc:
        logger.error("Upload scene reference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="场景参考图上传失败，请稍后重试") from exc


@router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await pipeline_scene_library_service.delete_profile(db, scene_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="场景档案不存在")
    return {
        "success": True,
        "message": "场景档案已删除",
    }


@router.delete("/characters/{character_id}")
async def delete_character(character_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await pipeline_character_library_service.delete_profile(db, character_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="角色档案不存在")
    return {
        "success": True,
        "message": "角色档案已删除",
    }


class RenderProjectRequest(BaseModel):
    """渲染与合成请求。"""

    project_id: str = Field(default="", description="项目 ID")
    project_title: str = Field(default="未命名项目")
    provider: str = Field(default="auto", description="视频生成 provider")
    resolution: str = Field(default="720p", description="输出分辨率")
    aspect_ratio: str = Field(default="16:9", description="画幅比例")
    watermark: bool = Field(default=False, description="是否添加水印")
    provider_model: str = Field(default="", description="provider 模型 ID")
    camera_fixed: bool = Field(default=False, description="是否固定镜头")
    generate_audio: bool = Field(default=True, description="是否启用视频模型自带音频")
    return_last_frame: bool = Field(default=False, description="是否返回尾帧")
    auto_continue_segments: bool = Field(default=False, description="是否自动连续生成所有片段")
    service_tier: str = Field(default="default", description="provider 服务等级")
    seed: Optional[int] = Field(default=None, description="随机种子")
    selected_character_ids: List[str] = Field(default_factory=list, description="已选角色档案 ID")
    selected_scene_ids: List[str] = Field(default_factory=list, description="已选场景档案 ID")
    character_profiles: List[CharacterProfilePayload] = Field(default_factory=list, description="直接传入的角色档案")
    scene_profiles: List[SceneProfilePayload] = Field(default_factory=list, description="直接传入的场景档案")
    segments: List[SegmentPayload] = Field(..., min_length=1)
    keyframes: List[KeyframeBundlePayload] = Field(default_factory=list)


class ResumeRenderTaskRequest(BaseModel):
    auto_continue_segments: Optional[bool] = Field(default=None, description="是否切换为自动连续生成剩余片段")


@router.post("/upload-reference")
async def upload_reference(file: UploadFile = File(...)):
    """上传参考图，供剧本生成和首尾帧阶段使用。"""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        result = await pipeline_workflow_service.save_reference_upload(
            filename=file.filename or "reference.png",
            content=content,
            content_type=file.content_type,
        )
        return {
            "success": True,
            "message": "参考图上传成功",
            **result,
        }
    except Exception as exc:
        logger.error("Upload reference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="参考图上传失败，请稍后重试") from exc


@router.post("/generate-script")
async def generate_script(
    request: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """生成完整剧本，并返回可编辑文本。"""
    start_time = time.time()

    try:
        resolved_profiles = await _resolve_character_profiles(
            db,
            selected_character_ids=request.selected_character_ids,
            direct_character_profiles=[profile.model_dump() for profile in request.character_profiles],
        )
        if not resolved_profiles and not request.selected_character_ids and not request.character_profiles:
            resolved_profiles = await pipeline_character_library_service.list_profiles(db)
        resolved_scene_profiles = await _resolve_scene_profiles(
            db,
            selected_scene_ids=request.selected_scene_ids,
            direct_scene_profiles=[profile.model_dump() for profile in request.scene_profiles],
        )
        if not resolved_scene_profiles and not request.selected_scene_ids and not request.scene_profiles:
            resolved_scene_profiles = await pipeline_scene_library_service.list_profiles(db)
        result = await pipeline_workflow_service.generate_script(
            request.user_input,
            style=request.style,
            target_total_duration=request.target_total_duration,
            selected_character_ids=request.selected_character_ids,
            character_profiles=resolved_profiles,
            selected_scene_ids=request.selected_scene_ids,
            scene_profiles=resolved_scene_profiles,
            reference_images=[reference.model_dump() for reference in request.reference_images],
            generation_intent=request.generation_intent,
            character_resolution=request.character_resolution,
        )
        response_payload = {
            "success": True,
            "message": "完整剧本生成完成，请先审核后再进入拆分阶段",
            "processing_time": time.time() - start_time,
            **result,
        }
        existing_project = None
        if request.project_id:
            existing_project = await pipeline_project_service.get_project(db, current_user.id, request.project_id)
        if existing_project is None:
            existing_project = await pipeline_project_service.get_current_project(db, current_user.id)

        existing_state = existing_project.get("state") if isinstance(existing_project, dict) else {}
        if not isinstance(existing_state, dict):
            existing_state = {}
        summary_payload = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        existing_project_title = existing_project.get("project_title") if isinstance(existing_project, dict) else ""

        project_title = str(
            summary_payload.get("title")
            or existing_project_title
            or "未命名项目"
        ).strip() or "未命名项目"
        summary_text = str(summary_payload.get("synopsis") or "").strip()
        project_state = {
            **existing_state,
            "currentStep": 1,
            "transitionDirection": "forward",
            "userInput": request.user_input,
            "stylePreference": request.style,
            "projectTitle": project_title,
            "targetTotalDuration": request.target_total_duration,
            "constraintCharacterIds": request.selected_character_ids,
            "constraintSceneIds": request.selected_scene_ids,
            "selectedCharacterIds": result.get("selected_character_ids") or request.selected_character_ids,
            "selectedSceneIds": result.get("selected_scene_ids") or request.selected_scene_ids,
            "referenceImages": [reference.model_dump() for reference in request.reference_images],
            "generatedScript": response_payload,
            "manualCharacterProfiles": [],
            "savedTemporaryCharacterIds": existing_state.get("savedTemporaryCharacterIds", []),
            "scriptDraft": str(result.get("script_text") or ""),
            "scriptSummary": result.get("summary") or None,
            "segments": existing_state.get("segments", []),
            "splitValidationReport": existing_state.get("splitValidationReport"),
            "keyframes": existing_state.get("keyframes", []),
            "renderTaskId": existing_state.get("renderTaskId"),
            "renderStatus": existing_state.get("renderStatus"),
        }
        await pipeline_project_service.save_current_project(
            db,
            project_id=request.project_id,
            user_id=current_user.id,
            project_title=project_title,
            current_step=1,
            state=project_state,
            status="draft",
            last_render_task_id=str(existing_project.get("last_render_task_id") or "") if isinstance(existing_project, dict) else "",
            summary=summary_text,
        )
        return response_payload
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except Exception as exc:
        logger.error("Generate script failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="剧本生成失败，请稍后重试") from exc


@router.post("/prepare-characters")
async def prepare_characters(request: PrepareCharactersRequest, db: AsyncSession = Depends(get_db)):
    start_time = time.time()
    try:
        resolved_profiles = await _resolve_character_profiles(
            db,
            selected_character_ids=request.selected_character_ids,
            direct_character_profiles=[profile.model_dump() for profile in request.character_profiles],
        )
        if not resolved_profiles and not request.selected_character_ids and not request.character_profiles:
            resolved_profiles = await pipeline_character_library_service.list_profiles(db)
        result = await pipeline_workflow_service.prepare_character_resolution(
            request.user_input,
            style=request.style,
            target_total_duration=request.target_total_duration,
            selected_character_ids=request.selected_character_ids,
            character_profiles=resolved_profiles,
        )
        return {
            "success": True,
            "message": "角色确认信息已准备完成",
            "processing_time": time.time() - start_time,
            **result,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except Exception as exc:
        logger.error("Prepare characters failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="角色准备失败，请稍后重试") from exc


@router.post("/split-script")
async def split_script(
    request: SplitScriptRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """对审核后的剧本进行拆分。"""
    start_time = time.time()

    try:
        existing_project = None
        if request.project_id:
            existing_project = await pipeline_project_service.get_project(db, current_user.id, request.project_id)
        if existing_project is None:
            existing_project = await pipeline_project_service.get_current_project(db, current_user.id)

        existing_state = existing_project.get("state") if isinstance(existing_project, dict) else {}
        if not isinstance(existing_state, dict):
            existing_state = {}

        if existing_state and _split_request_matches_state(
            existing_state,
            script_text=request.script_text,
            max_segment_duration=request.max_segment_duration,
            target_total_duration=request.target_total_duration,
        ):
            cached_result = _build_split_response_from_state(existing_state)
            if cached_result is not None:
                return {
                    "success": True,
                    "message": "已直接复用上一次成功的剧本拆分结果，避免重复调用模型。",
                    "processing_time": time.time() - start_time,
                    **cached_result,
                }

        result = await pipeline_workflow_service.split_script(
            request.script_text,
            max_segment_duration=request.max_segment_duration,
            target_total_duration=request.target_total_duration,
        )

        project_title = str(
            (existing_project or {}).get("project_title")
            or existing_state.get("projectTitle")
            or "未命名项目"
        ).strip() or "未命名项目"
        summary_payload = existing_state.get("scriptSummary") if isinstance(existing_state.get("scriptSummary"), dict) else {}
        summary_text = str(summary_payload.get("synopsis") or (existing_project or {}).get("summary") or "").strip()
        split_signature = _build_split_state_signature(
            script_text=request.script_text,
            max_segment_duration=request.max_segment_duration,
            target_total_duration=request.target_total_duration,
        )
        project_state = {
            **existing_state,
            "currentStep": 2,
            "transitionDirection": "forward",
            "projectTitle": project_title,
            "scriptDraft": request.script_text,
            "maxSegmentDuration": request.max_segment_duration,
            "targetTotalDuration": request.target_total_duration,
            "segments": result.get("segments") or [],
            "splitValidationReport": result.get("validation_report"),
            "continuityPoints": result.get("continuity_points") or [],
            "splitRequestSignature": split_signature,
            "keyframes": [],
            "renderTaskId": None,
            "renderStatus": None,
        }
        await pipeline_project_service.save_current_project(
            db,
            project_id=request.project_id,
            user_id=current_user.id,
            project_title=project_title,
            current_step=2,
            state=project_state,
            status="draft",
            last_render_task_id="",
            summary=summary_text,
        )

        return {
            "success": True,
            "message": "剧本拆分完成，请审核片段后生成首尾帧",
            "processing_time": time.time() - start_time,
            **result,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except Exception as exc:
        logger.error("Split script failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="剧本拆分失败，请稍后重试") from exc


@router.post("/generate-keyframes")
async def generate_keyframes(request: GenerateKeyframesRequest, db: AsyncSession = Depends(get_db)):
    """为审核后的片段生成首尾帧。"""
    start_time = time.time()

    try:
        resolved_profiles = await _resolve_character_profiles(
            db,
            selected_character_ids=request.selected_character_ids,
            direct_character_profiles=[profile.model_dump() for profile in request.character_profiles],
        )
        resolved_scene_profiles = await _resolve_scene_profiles(
            db,
            selected_scene_ids=request.selected_scene_ids,
            direct_scene_profiles=[profile.model_dump() for profile in request.scene_profiles],
        )
        result = await pipeline_workflow_service.generate_keyframes(
            project_title=request.project_title,
            segments=[segment.model_dump() for segment in request.segments],
            style=request.style,
            selected_character_ids=request.selected_character_ids,
            character_profiles=resolved_profiles,
            selected_scene_ids=request.selected_scene_ids,
            scene_profiles=resolved_scene_profiles,
            reference_images=[reference.model_dump() for reference in request.reference_images],
        )
        return {
            "processing_time": time.time() - start_time,
            **result,
        }
    except Exception as exc:
        logger.error("Generate keyframes failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="关键帧生成失败，请稍后重试") from exc


@router.post("/render")
async def render_project(
    request: RenderProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """发起片段渲染和最终合成。"""
    try:
        if request.provider == "kling" and not kling_credentials_configured():
            raise MissingProviderConfigError(
                code=KLING_API_KEY_ERROR_CODE,
                message="未配置 KLING_ACCESS_KEY / KLING_SECRET_KEY，无法调用可灵视频生成。",
            )
        if request.provider == "doubao" and not get_effective_doubao_api_key():
            raise MissingProviderConfigError(
                code=DOUBAO_API_KEY_ERROR_CODE,
                message="未配置 DOUBAO_API_KEY，无法调用豆包视频生成。可在前端临时填写后重试，或改用 local 预览模式。",
            )
        if request.provider == "auto" and not kling_credentials_configured() and not get_effective_doubao_api_key():
            raise MissingProviderConfigError(
                code=KLING_API_KEY_ERROR_CODE,
                message="未配置可灵或豆包视频生成凭证。请先配置 KLING_ACCESS_KEY / KLING_SECRET_KEY，或在前端临时填写 DOUBAO_API_KEY 后重试，或改用 local 预览模式。",
            )
        existing_task_state = await pipeline_workflow_service.find_active_render_task_for_project(
            user_id=current_user.id,
            project_id=request.project_id,
        )
        if existing_task_state is not None:
            return {
                "success": True,
                "message": "当前项目已有进行中的渲染任务，已直接复用现有任务，避免重复生成。",
                "task_id": existing_task_state.task_id,
                "status": existing_task_state.status,
                "current_step": existing_task_state.current_step,
                "renderer": existing_task_state.renderer,
            }

        resolved_character_profiles = await _resolve_character_profiles(
            db,
            selected_character_ids=request.selected_character_ids,
            direct_character_profiles=[profile.model_dump() for profile in request.character_profiles],
        )
        resolved_scene_profiles = await _resolve_scene_profiles(
            db,
            selected_scene_ids=request.selected_scene_ids,
            direct_scene_profiles=[profile.model_dump() for profile in request.scene_profiles],
        )
        task_state = await pipeline_workflow_service.create_render_task(
            user_id=current_user.id,
            project_id=request.project_id,
            project_title=request.project_title,
            segments=[segment.model_dump() for segment in request.segments],
            keyframes=[bundle.model_dump() for bundle in request.keyframes],
            character_profiles=resolved_character_profiles,
            scene_profiles=resolved_scene_profiles,
            render_config={
                "provider": request.provider,
                "resolution": request.resolution,
                "aspect_ratio": request.aspect_ratio,
                "watermark": request.watermark,
                "provider_model": request.provider_model,
                "camera_fixed": request.camera_fixed,
                "generate_audio": request.generate_audio,
                "return_last_frame": request.return_last_frame,
                "auto_continue_segments": request.auto_continue_segments,
                "service_tier": request.service_tier,
                "seed": request.seed,
            },
        )
        await pipeline_workflow_service.start_render_task(task_state.task_id)
        return {
            "success": True,
            "message": (
                "渲染任务已在当前服务进程启动"
                if settings.pipeline_uses_local_render_dispatch
                else "渲染任务已提交到队列"
            ),
            "task_id": task_state.task_id,
            "status": task_state.status,
            "current_step": task_state.current_step,
            "renderer": task_state.renderer,
        }
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except Exception as exc:
        logger.error("Render project failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="渲染任务创建失败，请稍后重试") from exc


@router.get("/render/{task_id}")
async def get_render_status(
    task_id: str,
    current_user=Depends(get_current_user),
):
    """查询渲染任务状态。"""
    result = await pipeline_workflow_service.get_render_task(task_id, user_id=current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.post("/render/{task_id}/cancel")
async def cancel_render_task(
    task_id: str,
    current_user=Depends(get_current_user),
):
    """取消渲染任务。"""
    try:
        state = await pipeline_workflow_service.cancel_render_task(task_id, user_id=current_user.id)
        if not state:
            raise HTTPException(status_code=404, detail="任务不存在")
        return state.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Cancel render task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="取消渲染任务失败，请稍后重试") from exc


@router.post("/render/{task_id}/pause")
async def pause_render_task(
    task_id: str,
    current_user=Depends(get_current_user),
):
    """暂停渲染任务。"""
    try:
        state = await pipeline_workflow_service.pause_render_task(task_id, user_id=current_user.id)
        if not state:
            raise HTTPException(status_code=404, detail="任务不存在")
        return state.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Pause render task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="暂停渲染任务失败，请稍后重试") from exc


@router.post("/render/{task_id}/resume")
async def resume_render_task(
    task_id: str,
    request: ResumeRenderTaskRequest = Body(default_factory=ResumeRenderTaskRequest),
    current_user=Depends(get_current_user),
):
    """继续已暂停的渲染任务。"""
    try:
        state = await pipeline_workflow_service.resume_render_task(
            task_id,
            user_id=current_user.id,
            auto_continue_segments=request.auto_continue_segments,
        )
        if not state:
            raise HTTPException(status_code=404, detail="任务不存在")
        return state.to_dict()
    except HTTPException:
        raise
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Resume render task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="继续渲染任务失败，请稍后重试") from exc


@router.post("/render/{task_id}/clips/{clip_number}/retry")
async def retry_render_clip(
    task_id: str,
    clip_number: int,
    current_user=Depends(get_current_user),
):
    """单独重生成某个片段。"""
    try:
        state = await pipeline_workflow_service.retry_render_clip(
            task_id,
            clip_number=clip_number,
            user_id=current_user.id,
        )
        if not state:
            raise HTTPException(status_code=404, detail="任务不存在")
        return state.to_dict()
    except HTTPException:
        raise
    except MissingProviderConfigError as exc:
        _raise_provider_config_http_exception(exc)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Retry render clip failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="片段重生成失败，请稍后重试") from exc


@router.post("/render/{task_id}/retry")
async def retry_render_task(
    task_id: str,
    current_user=Depends(get_current_user),
):
    """重试失败或已取消的渲染任务。"""
    try:
        task_state = await pipeline_workflow_service.retry_render_task(task_id, user_id=current_user.id)
        if not task_state:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "success": True,
            "message": (
                "渲染任务已在当前服务进程重新启动"
                if settings.pipeline_uses_local_render_dispatch
                else "渲染任务已重新提交到队列"
            ),
            "task_id": task_state.task_id,
            "status": task_state.status,
            "current_step": task_state.current_step,
            "renderer": task_state.renderer,
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Retry render task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="重试渲染任务失败，请稍后重试") from exc


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "script-pipeline",
        "mode": "stepwise-e2e-workflow",
        "runtime_mode": settings.PIPELINE_RUNTIME_MODE,
        "render_dispatch_mode": settings.pipeline_render_dispatch_mode,
    }
