#!/usr/bin/env python3
"""
分步式剧本工作流服务。

当前主链路：
1. 用户输入描述、偏好和参考图
2. 生成完整剧本并给前端审核
3. 拆分视频片段并给前端审核
4. 生成并审核片段首尾帧
5. 基于审核后的片段和首尾帧生成视频
6. 合并成完整成片并返回结果

实现策略：
- 主链路统一通过本服务编排，不再依赖旧散乱路由
- 优先复用 NanoBanana / Doubao / FFmpeg 等历史能力
- 若缺少外部依赖或调用失败，自动回退到本地占位渲染，保证流程可跑
"""

from __future__ import annotations

import asyncio
import base64
import html
import logging
import os
import re
import textwrap
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from xml.sax.saxutils import escape

import httpx
from sqlalchemy import select, update

from app.core.config import settings
from app.core.provider_keys import (
    get_effective_doubao_api_key,
    get_effective_kling_credentials,
    kling_credentials_configured,
    require_doubao_api_key,
    require_kling_credentials,
)
from app.db.base import AsyncSessionLocal
from app.models.pipeline_project import PipelineProject
from app.models.pipeline_render_task import PipelineRenderTask
from app.services.audio_renderer import ProjectAudioRenderer
from app.services.preferred_image_generation import PreferredImageGenerationClient
from app.services.script_generator import FullScript, ScriptGenerator
from app.services.script_splitter import ScriptSplitter, SplitConfig
from app.services.video_merger import MergeOptions, VideoMergerService, VideoSegment as MergedVideoSegment
from app.utils.image_variants import build_upload_url, ensure_thumbnail_for_path

logger = logging.getLogger(__name__)

MAX_VIDEO_SEGMENT_DURATION = 10.0
MAX_KEYFRAME_CHARACTER_ANCHOR_IMAGES = 6
MAX_VIDEO_CHARACTER_ANCHOR_IMAGES = 4
RECOVERABLE_QUEUED_STEPS = {
    "",
    "等待开始",
    "等待重新投递",
    "任务中断",
    "任务入队失败",
}
CLAIMABLE_QUEUED_STEPS = set(RECOVERABLE_QUEUED_STEPS)
DISPATCHING_STATUS = "dispatching"
DISPATCHING_STEP = "正在提交到队列"
SUBMITTED_TO_QUEUE_STEP = "已提交到队列，等待 worker 处理"
SUBMITTED_TO_LOCAL_STEP = "已在当前服务进程启动"


class RenderTaskCancelledError(RuntimeError):
    """渲染任务被用户取消。"""


class RenderTaskPausedError(RuntimeError):
    """渲染任务被用户暂停。"""


@dataclass
class ReferenceAsset:
    """用户上传或系统引用的参考图片。"""

    id: str
    url: str
    filename: str
    original_filename: str = ""
    content_type: str = "image/png"
    size: int = 0
    source: str = "upload"


@dataclass
class KeyframeAsset:
    """片段关键帧资源。"""

    asset_url: str
    asset_type: str
    asset_filename: str
    prompt: str
    source: str
    thumbnail_url: str = ""
    status: str = "completed"
    notes: str = ""


@dataclass
class SegmentKeyframes:
    """单个片段的首尾帧。"""

    segment_number: int
    title: str
    start_frame: KeyframeAsset
    end_frame: KeyframeAsset
    continuity_notes: str = ""
    status: str = "ready"


@dataclass
class RenderedClip:
    """渲染完成后的片段资源。"""

    clip_number: int
    title: str
    duration: float
    status: str = "queued"
    asset_url: str = ""
    asset_type: str = ""
    asset_filename: str = ""
    description: str = ""
    video_prompt: str = ""
    provider: str = ""
    error: str = ""


@dataclass
class RenderTaskState:
    """异步渲染任务状态。"""

    task_id: str
    user_id: str
    project_id: str
    project_title: str
    segments: List[Dict[str, Any]]
    keyframes: List[Dict[str, Any]]
    character_profiles: List[Dict[str, Any]]
    scene_profiles: List[Dict[str, Any]]
    render_config: Dict[str, Any]
    status: str = "queued"
    progress: float = 0.0
    current_step: str = "等待开始"
    renderer: str = "pending"
    clips: List[RenderedClip] = field(default_factory=list)
    final_output: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    warnings: List[str] = field(default_factory=list)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        last_completed_clip_number: Optional[int] = None
        next_clip_number: Optional[int] = None
        for clip in self.clips:
            if clip.status == "completed" and clip.asset_url:
                last_completed_clip_number = int(clip.clip_number)
                continue
            if clip.status not in {"completed", "failed", "cancelled"}:
                next_clip_number = int(clip.clip_number)
                break
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "project_title": self.project_title,
            "status": self.status,
            "progress": round(self.progress, 2),
            "current_step": self.current_step,
            "renderer": self.renderer,
            "clips": [asdict(clip) for clip in self.clips],
            "character_profiles": self.character_profiles,
            "scene_profiles": self.scene_profiles,
            "final_output": self.final_output,
            "fallback_used": self.fallback_used,
            "warnings": self.warnings,
            "render_config": self.render_config,
            "awaiting_confirmation": self.status == "paused" and self.current_step.startswith("等待确认继续生成片段"),
            "last_completed_clip_number": last_completed_clip_number,
            "next_clip_number": next_clip_number,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PipelineWorkflowService:
    """单主链路工作流服务。"""

    def __init__(self) -> None:
        self.generator = ScriptGenerator()
        self.tasks: Dict[str, RenderTaskState] = {}
        self.local_render_jobs: Dict[str, asyncio.Task[Any]] = {}
        self.output_root = Path(settings.UPLOAD_DIR) / "generated" / "pipeline"
        self.reference_root = Path(settings.UPLOAD_DIR) / "generated" / "references"
        self.identity_board_root = self.output_root / "identity_boards"
        self.image_generator = PreferredImageGenerationClient()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.reference_root.mkdir(parents=True, exist_ok=True)
        self.identity_board_root.mkdir(parents=True, exist_ok=True)

    def uses_local_render_dispatch(self) -> bool:
        return settings.pipeline_uses_local_render_dispatch

    async def save_reference_upload(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> Dict[str, Any]:
        """保存用户上传的参考图。"""
        suffix = Path(filename).suffix or ".png"
        asset_id = uuid.uuid4().hex
        safe_filename = f"{asset_id}{suffix}"
        target_dir = self.reference_root / datetime.now().strftime("%Y%m%d")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_filename
        target_path.write_bytes(content)
        thumbnail_path = ensure_thumbnail_for_path(target_path)

        asset = ReferenceAsset(
            id=asset_id,
            url=self._build_asset_url(target_path),
            filename=safe_filename,
            original_filename=filename,
            content_type=content_type,
            size=len(content),
            source="upload",
        )
        payload = asdict(asset)
        payload["thumbnail_url"] = build_upload_url(thumbnail_path) if thumbnail_path else ""
        return payload

    async def generate_script(
        self,
        user_input: str,
        *,
        style: str = "",
        target_total_duration: Optional[float] = None,
        selected_character_ids: Optional[List[str]] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        selected_scene_ids: Optional[List[str]] = None,
        scene_profiles: Optional[List[Dict[str, Any]]] = None,
        reference_images: Optional[List[Dict[str, Any]]] = None,
        generation_intent: Optional[Dict[str, Any]] = None,
        character_resolution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成完整剧本，并转换成可编辑文本。"""
        resolved_character_profiles = self._resolve_character_profiles(
            selected_character_ids=selected_character_ids or [],
            character_profiles=character_profiles or [],
        )
        selected_character_id_set = {
            str(profile_id).strip()
            for profile_id in (selected_character_ids or [])
            if str(profile_id).strip()
        }
        resolved_library_character_profiles = [
            profile for profile in resolved_character_profiles if str(profile.get("id") or "").strip() in selected_character_id_set
        ]
        resolved_temporary_character_profiles = [
            profile for profile in resolved_character_profiles if str(profile.get("id") or "").strip() not in selected_character_id_set
        ]
        resolved_scene_profiles = self._resolve_scene_profiles(
            selected_scene_ids=selected_scene_ids or [],
            scene_profiles=scene_profiles or [],
        )
        full_script = await self.generator.generate_full_script(
            user_input,
            style=style,
            target_total_duration=target_total_duration,
            character_profiles=resolved_character_profiles,
            scene_profiles=resolved_scene_profiles,
            reference_images=reference_images or [],
            generation_intent=generation_intent,
            character_resolution=character_resolution,
            library_character_profiles=resolved_library_character_profiles,
            temporary_character_profiles=resolved_temporary_character_profiles,
        )
        script_text = self.format_full_script_text(full_script)
        matched_character_profiles = full_script.active_character_profiles or full_script.matched_character_profiles or resolved_character_profiles
        matched_scene_profiles = full_script.matched_scene_profiles or resolved_scene_profiles

        return {
            "original_input": user_input,
            "style": style,
            "selected_character_ids": [profile["id"] for profile in matched_character_profiles if profile.get("id")],
            "selected_scene_ids": [profile["id"] for profile in matched_scene_profiles if profile.get("id")],
            "character_profiles": matched_character_profiles,
            "library_character_profiles": full_script.library_character_profiles or [],
            "temporary_character_profiles": full_script.temporary_character_profiles or [],
            "scene_profiles": matched_scene_profiles,
            "character_resolution": full_script.character_resolution or {},
            "reference_images": reference_images or [],
            "summary": self._build_script_summary(full_script),
            "full_script": asdict(full_script),
            "script_text": script_text,
        }

    async def prepare_character_resolution(
        self,
        user_input: str,
        *,
        style: str = "",
        target_total_duration: Optional[float] = None,
        selected_character_ids: Optional[List[str]] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        resolved_character_profiles = self._resolve_character_profiles(
            selected_character_ids=selected_character_ids or [],
            character_profiles=character_profiles or [],
        )
        resolution = await self.generator.prepare_character_resolution(
            user_input=user_input,
            style=style,
            target_total_duration=target_total_duration,
            character_profiles=resolved_character_profiles,
        )
        return {
            "user_input": user_input,
            "style": style,
            "target_total_duration": target_total_duration,
            **resolution,
        }

    async def split_script(
        self,
        script_text: str,
        *,
        max_segment_duration: float = 10.0,
        target_total_duration: Optional[float] = None,
    ) -> Dict[str, Any]:
        """将审核后的完整剧本拆分成片段。"""
        logger.info(
            "Split script request received. max_segment_duration=%s target_total_duration=%s\n-----SCRIPT START-----\n%s\n-----SCRIPT END-----",
            max_segment_duration,
            target_total_duration,
            script_text,
        )
        splitter = ScriptSplitter(
            SplitConfig(
                max_segment_duration=min(float(max_segment_duration), MAX_VIDEO_SEGMENT_DURATION),
                min_segment_duration=3.0,
                prefer_scene_boundary=True,
                preserve_dialogue=True,
                smooth_transition=True,
            )
        )

        split_result = await splitter.split_script(
            script=script_text,
            target_duration=target_total_duration,
        )

        segments = [asdict(segment) for segment in split_result.segments]
        return {
            "script_text": script_text,
            "total_duration": split_result.total_duration,
            "segment_count": split_result.segment_count,
            "segments": segments,
            "continuity_points": split_result.continuity_points,
            "validation_report": split_result.validation_report,
        }

    async def generate_keyframes(
        self,
        *,
        project_title: str,
        segments: List[Dict[str, Any]],
        style: str = "",
        selected_character_ids: Optional[List[str]] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        selected_scene_ids: Optional[List[str]] = None,
        scene_profiles: Optional[List[Dict[str, Any]]] = None,
        reference_images: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """为片段生成首尾帧，并保证片段间首尾连续。"""
        normalized_segments = [self._normalize_segment(segment, index) for index, segment in enumerate(segments)]
        normalized_references = [self._normalize_reference_image(reference, index) for index, reference in enumerate(reference_images or [])]
        resolved_character_profiles = self._resolve_character_profiles(
            selected_character_ids=selected_character_ids or [],
            character_profiles=character_profiles or [],
        )
        resolved_scene_profiles = self._resolve_scene_profiles(
            selected_scene_ids=selected_scene_ids or [],
            scene_profiles=scene_profiles or [],
        )

        task_dir = self.output_root / uuid.uuid4().hex / "keyframes"
        task_dir.mkdir(parents=True, exist_ok=True)

        keyframe_bundles: List[SegmentKeyframes] = []
        generated_start_frame_count = 0

        for index, segment in enumerate(normalized_segments):
            should_pre_generate_start_frame = bool(segment.get("pre_generate_start_frame", False) or index == 0)
            start_frame_reason = str(segment.get("start_frame_generation_reason") or "")
            if should_pre_generate_start_frame:
                start_frame = await self._generate_keyframe_asset(
                    task_dir=task_dir,
                    segment=segment,
                    frame_kind="start",
                    style=style,
                    character_profiles=resolved_character_profiles,
                    scene_profiles=resolved_scene_profiles,
                    reference_images=normalized_references,
                    base_asset=None,
                )
                generated_start_frame_count += 1
                if start_frame_reason == "new_character_entry":
                    start_notes = "该段是新角色首次正式登场段，额外预生成首帧以突出角色造型并稳定后续角色连续性"
                    if start_frame.notes:
                        start_frame.notes = f"{start_frame.notes} | 新角色首次正式登场段的额外首帧锚点"
                    else:
                        start_frame.notes = "新角色首次正式登场段的额外首帧锚点"
                elif index == 0:
                    start_notes = "首段首帧由 NanoBanana/参考图生成，作为整条视频的起始画面"
                else:
                    start_notes = "该段首帧由 NanoBanana/参考图额外预生成，作为角色和镜头起始锚点"
            else:
                start_frame = KeyframeAsset(
                    asset_url="",
                    asset_type="image/png",
                    asset_filename="",
                    prompt="",
                    source="runtime-last-frame",
                    status="pending",
                    notes="该片段首帧不再单独生成，渲染时直接复用上一片段返回的尾帧",
                )
                start_notes = "渲染阶段自动复用上一片段尾帧作为本片段首帧"

            end_frame = KeyframeAsset(
                asset_url="",
                asset_type="image/png",
                asset_filename="",
                prompt="",
                source="provider-return-last-frame",
                status="pending",
                notes="该片段尾帧由豆包视频接口在生成完成后返回，用于串联下一片段",
            )

            bundle = SegmentKeyframes(
                segment_number=segment["segment_number"],
                title=segment["title"],
                start_frame=start_frame,
                end_frame=end_frame,
                continuity_notes=f"{start_notes}；片段尾帧由视频接口返回，并自动作为下一片段首帧参考",
            )
            keyframe_bundles.append(bundle)

        message = "已生成首段首帧，后续片段将在渲染时自动串联上一段尾帧"
        if generated_start_frame_count > 1:
            message = "已按分段规则生成多张首帧，其余片段将在渲染时自动串联上一段尾帧"

        return {
            "success": True,
            "message": message,
            "project_title": project_title or "未命名项目",
            "style": style,
            "selected_character_ids": [profile["id"] for profile in resolved_character_profiles if profile.get("id")],
            "selected_scene_ids": [profile["id"] for profile in resolved_scene_profiles if profile.get("id")],
            "character_profiles": resolved_character_profiles,
            "scene_profiles": resolved_scene_profiles,
            "reference_images": normalized_references,
            "keyframes": [asdict(bundle) for bundle in keyframe_bundles],
        }

    async def create_render_task(
        self,
        *,
        user_id: str,
        project_id: str = "",
        project_title: str,
        segments: List[Dict[str, Any]],
        keyframes: List[Dict[str, Any]],
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        scene_profiles: Optional[List[Dict[str, Any]]] = None,
        render_config: Optional[Dict[str, Any]] = None,
    ) -> RenderTaskState:
        """创建异步渲染任务。"""
        normalized_segments = [self._normalize_segment(segment, index) for index, segment in enumerate(segments)]
        normalized_keyframes = [self._normalize_keyframe_bundle(bundle, index) for index, bundle in enumerate(keyframes or [])]
        config = self._normalize_render_config(render_config or {})
        config["audio_plan"] = self._build_project_audio_plan(
            segments=normalized_segments,
            character_profiles=character_profiles or [],
            scene_profiles=scene_profiles or [],
            render_config=config,
        )
        task_id = uuid.uuid4().hex
        renderer = self._choose_render_provider(config)

        state = RenderTaskState(
            task_id=task_id,
            user_id=user_id,
            project_id=project_id,
            project_title=project_title or "未命名项目",
            segments=normalized_segments,
            keyframes=normalized_keyframes,
            character_profiles=self._resolve_character_profiles(
                selected_character_ids=[],
                character_profiles=character_profiles or [],
            ),
            scene_profiles=self._resolve_scene_profiles(
                selected_scene_ids=[],
                scene_profiles=scene_profiles or [],
            ),
            render_config=config,
            renderer=renderer,
            clips=[
                RenderedClip(
                    clip_number=segment["segment_number"],
                    title=segment["title"],
                    duration=float(segment["duration"]),
                    status="queued",
                    description=segment["description"],
                    video_prompt=segment["video_prompt"],
                )
                for segment in normalized_segments
            ],
        )

        self.tasks[task_id] = state
        await self._persist_render_task_state(user_id=user_id, state=state)
        return state

    async def find_active_render_task_for_project(
        self,
        *,
        user_id: str,
        project_id: str,
    ) -> Optional[RenderTaskState]:
        normalized_project_id = str(project_id or "").strip()
        if not normalized_project_id:
            return None

        active_statuses = {"queued", DISPATCHING_STATUS, "processing", "paused"}
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineRenderTask.id)
                .where(
                    PipelineRenderTask.user_id == user_id,
                    PipelineRenderTask.project_id == normalized_project_id,
                    PipelineRenderTask.status.in_(tuple(active_statuses)),
                )
                .order_by(PipelineRenderTask.updated_at.desc(), PipelineRenderTask.created_at.desc())
                .limit(1)
            )
            task_id = result.scalar_one_or_none()

        if not task_id:
            return None

        state = self.tasks.get(task_id)
        if state is not None:
            return state
        return await self._load_render_task_state(task_id)

    async def start_render_task(self, task_id: str, *, mark_failed_on_enqueue_error: bool = True) -> None:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None:
            raise RuntimeError(f"渲染任务不存在: {task_id}")
        if state.status == "completed":
            return
        if state.status in {"processing", DISPATCHING_STATUS}:
            logger.info("Render task already processing: %s", task_id)
            return

        claimed_state = await self._claim_render_task_for_dispatch(task_id)
        if claimed_state is None:
            latest_state = await self._load_render_task_state(task_id)
            latest_status = latest_state.status if latest_state else "unknown"
            logger.info("Render task already claimed or submitted elsewhere: %s (%s)", task_id, latest_status)
            return
        state = claimed_state

        if self.uses_local_render_dispatch():
            await self._start_render_task_locally(
                task_id=task_id,
                state=state,
                mark_failed_on_enqueue_error=mark_failed_on_enqueue_error,
            )
            return

        try:
            from app.workers.render_tasks import enqueue_render_task
            from app.workers.render_tasks import revoke_render_task

            enqueue_render_task(task_id)
            try:
                await self._ensure_render_task_can_continue(task_id, state)
            except (RenderTaskCancelledError, RenderTaskPausedError):
                revoke_render_task(task_id, terminate=False)
                return
            state.status = "queued"
            state.current_step = SUBMITTED_TO_QUEUE_STEP
            state.error = ""
            state.touch()
            await self._persist_render_task_state(state=state)
        except Exception as exc:
            logger.error("Failed to enqueue render task %s: %s", task_id, exc, exc_info=True)
            state.status = "failed" if mark_failed_on_enqueue_error else "queued"
            state.current_step = "任务入队失败" if mark_failed_on_enqueue_error else "等待重新投递"
            state.error = str(exc)
            state.touch()
            await self._persist_render_task_state(state=state)
            raise

    async def _start_render_task_locally(
        self,
        *,
        task_id: str,
        state: RenderTaskState,
        mark_failed_on_enqueue_error: bool,
    ) -> None:
        existing_job = self.local_render_jobs.get(task_id)
        if existing_job is not None and not existing_job.done():
            logger.info("Render task already running locally: %s", task_id)
            return

        try:
            await self._ensure_render_task_can_continue(task_id, state)
            state.status = "queued"
            state.current_step = SUBMITTED_TO_LOCAL_STEP
            state.error = ""
            state.touch()
            await self._persist_render_task_state(state=state)
            self.local_render_jobs[task_id] = asyncio.create_task(
                self._run_render_task_in_local_process(task_id),
                name=f"pipeline-render-{task_id}",
            )
        except (RenderTaskCancelledError, RenderTaskPausedError):
            return
        except Exception as exc:
            logger.error("Failed to start local render task %s: %s", task_id, exc, exc_info=True)
            state.status = "failed" if mark_failed_on_enqueue_error else "queued"
            state.current_step = "任务启动失败" if mark_failed_on_enqueue_error else "等待重新投递"
            state.error = str(exc)
            state.touch()
            await self._persist_render_task_state(state=state)
            raise

    async def _run_render_task_in_local_process(self, task_id: str) -> None:
        try:
            await self.run_render_task(task_id)
        except RenderTaskPausedError:
            logger.info("Local render task paused before execution: %s", task_id)
        except RenderTaskCancelledError:
            logger.info("Local render task cancelled before execution: %s", task_id)
        except asyncio.CancelledError:
            logger.info("Local render coroutine cancelled: %s", task_id)
            raise
        except Exception as exc:
            logger.error("Local render task crashed unexpectedly: %s", exc, exc_info=True)
            try:
                await self.mark_render_task_failed(task_id, error=str(exc), current_step="失败")
            except Exception:
                logger.error("Failed to persist local render crash state for %s", task_id, exc_info=True)
        finally:
            self.local_render_jobs.pop(task_id, None)

    async def run_render_task(self, task_id: str) -> None:
        """执行片段渲染与最终合成。"""
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None:
            raise RuntimeError(f"渲染任务不存在: {task_id}")
        await self._ensure_render_task_can_continue(task_id, state)

        state.status = "processing"
        state.current_step = "开始生成视频片段"
        state.progress = 5.0
        state.touch()
        await self._persist_render_task_state(state=state)

        task_dir = self.output_root / task_id / "render"
        task_dir.mkdir(parents=True, exist_ok=True)

        keyframe_map = {
            int(bundle["segment_number"]): bundle
            for bundle in state.keyframes
        }
        previous_last_frame: Optional[KeyframeAsset] = None
        active_clip_index: Optional[int] = None

        try:
            total_segments = len(state.segments)
            for index, segment in enumerate(state.segments):
                active_clip_index = index
                await self._ensure_render_task_can_continue(task_id, state)
                clip_number = segment["segment_number"]
                clip_state = state.clips[index]
                if clip_state.status == "completed" and clip_state.asset_url:
                    completed_bundle = keyframe_map.get(clip_number) or {}
                    completed_end_frame = dict(completed_bundle.get("end_frame") or {})
                    if str(completed_end_frame.get("asset_url") or "").strip():
                        previous_last_frame = KeyframeAsset(
                            asset_url=str(completed_end_frame.get("asset_url") or ""),
                            asset_type=str(completed_end_frame.get("asset_type") or "image/png"),
                            asset_filename=str(
                                completed_end_frame.get("asset_filename") or f"clip_{clip_number:02d}_last_frame.png"
                            ),
                            prompt=str(completed_end_frame.get("prompt") or f"{segment['title']} 尾帧"),
                            source=str(completed_end_frame.get("source") or "provider-return-last-frame"),
                            status=str(completed_end_frame.get("status") or "completed"),
                            notes=str(completed_end_frame.get("notes") or "沿用已完成片段的尾帧作为下一片段起始锚点"),
                        )
                    continue

                state.current_step = f"生成片段 {clip_number}/{total_segments}"
                state.progress = 5.0 + (index / max(total_segments, 1)) * 75.0
                clip_state.status = "processing"
                clip_state.error = ""
                state.touch()
                await self._persist_render_task_state(state=state)

                runtime_bundle = keyframe_map.get(clip_number)
                if previous_last_frame and self._should_reuse_previous_last_frame(runtime_bundle):
                    runtime_bundle = self._with_runtime_start_frame(
                        bundle=runtime_bundle,
                        segment=segment,
                        start_frame=previous_last_frame,
                    )
                    keyframe_map[clip_number] = runtime_bundle
                    self._sync_runtime_keyframe_state(
                        state=state,
                        clip_number=clip_number,
                        start_frame=previous_last_frame,
                    )

                clip_asset = await self._render_video_or_preview(
                    task_dir=task_dir,
                    segment=segment,
                    keyframe_bundle=runtime_bundle,
                    character_profiles=state.character_profiles,
                    scene_profiles=state.scene_profiles,
                    render_config=state.render_config,
                )
                await self._ensure_render_task_can_continue(task_id, state)

                clip_state.status = "completed"
                clip_state.asset_url = clip_asset["asset_url"]
                clip_state.asset_type = clip_asset["asset_type"]
                clip_state.asset_filename = clip_asset["asset_filename"]
                clip_state.provider = clip_asset.get("provider", "")
                clip_state.error = ""
                if clip_asset.get("provider") == "doubao-official-text-only":
                    warning = f"片段 {clip_number} 因参考图被风控，已降级为豆包纯文本视频生成"
                    if warning not in state.warnings:
                        state.warnings.append(warning)
                if "sanitized" in str(clip_asset.get("provider") or ""):
                    warning = f"片段 {clip_number} 因文本风控，已自动净化提示词后重试"
                    if warning not in state.warnings:
                        state.warnings.append(warning)
                previous_last_frame = self._build_runtime_last_frame_asset(
                    clip_number=clip_number,
                    segment_title=segment["title"],
                    clip_asset=clip_asset,
                )
                if previous_last_frame:
                    self._sync_runtime_keyframe_state(
                        state=state,
                        clip_number=clip_number,
                        end_frame=previous_last_frame,
                    )
                state.touch()
                await self._persist_render_task_state(state=state)

                if self._should_wait_for_clip_confirmation(
                    state=state,
                    completed_index=index,
                    total_segments=total_segments,
                ):
                    next_clip_number = state.segments[index + 1]["segment_number"]
                    state.status = "paused"
                    state.current_step = f"等待确认继续生成片段 {next_clip_number}/{total_segments}"
                    state.progress = 5.0 + ((index + 1) / max(total_segments, 1)) * 75.0
                    state.error = ""
                    state.touch()
                    await self._persist_render_task_state(state=state)
                    return

            await self._ensure_render_task_can_continue(task_id, state)
            state.current_step = "合并最终成片"
            state.progress = 85.0
            state.touch()
            await self._persist_render_task_state(state=state)

            if self._can_merge_as_video(state.clips):
                final_output = await self._merge_video_clips(
                    task_dir=task_dir,
                    clips=state.clips,
                    project_title=state.project_title,
                    render_config=state.render_config,
                )
            else:
                if state.renderer == "local-preview":
                    final_output = await self._merge_preview_assets(
                        task_dir=task_dir,
                        clips=state.clips,
                        project_title=state.project_title,
                        segments=state.segments,
                    )
                else:
                    raise RuntimeError("存在未生成成功的视频片段，已停止最终合成")

            await self._ensure_render_task_can_continue(task_id, state)
            # External project audio rendering is temporarily disabled.
            # Keep the provider-native audio behavior from the video model itself.
            if bool(state.render_config.get("generate_audio", True)):
                final_output["audio"] = {
                    "status": "provider-native",
                    "strategy": "provider_native",
                    "message": "当前已跳过项目级音频后处理，保留视频模型自带的音频能力。",
                }
            else:
                final_output["audio"] = {
                    "status": "disabled",
                    "strategy": "mute",
                    "message": "已关闭音频生成，本次仅输出纯视频。",
                }
            await self._ensure_render_task_can_continue(task_id, state)
            state.final_output = final_output
            state.status = "completed"
            state.progress = 100.0
            state.current_step = "完成"
            state.touch()
            await self._persist_render_task_state(state=state)
        except RenderTaskPausedError:
            state.status = "paused"
            state.current_step = "已暂停"
            state.error = ""
            state.touch()
            await self._persist_render_task_state(state=state)
        except RenderTaskCancelledError:
            state.status = "cancelled"
            state.current_step = "已取消"
            state.error = ""
            self._mark_unfinished_clips_cancelled(state)
            state.touch()
            await self._persist_render_task_state(state=state)
        except Exception as exc:
            logger.error("Render task failed: %s", exc, exc_info=True)
            if active_clip_index is not None and active_clip_index < len(state.clips):
                state.clips[active_clip_index].status = "failed"
                state.clips[active_clip_index].error = str(exc)
            state.status = "failed"
            state.error = str(exc)
            state.current_step = "失败"
            state.touch()
            await self._persist_render_task_state(state=state)

    async def cancel_render_task(self, task_id: str, *, user_id: str) -> Optional[RenderTaskState]:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None or state.user_id != user_id:
            return None
        if state.status in {"completed", "failed", "cancelled"}:
            return state

        state.status = "cancelled"
        state.current_step = "已取消"
        state.error = ""
        self._mark_unfinished_clips_cancelled(state)
        state.touch()
        await self._persist_render_task_state(state=state)

        try:
            from app.workers.render_tasks import revoke_render_task

            revoke_render_task(task_id, terminate=False)
        except Exception as exc:
            logger.warning("Failed to revoke render task %s: %s", task_id, exc)
        return state

    async def pause_render_task(self, task_id: str, *, user_id: str) -> Optional[RenderTaskState]:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None or state.user_id != user_id:
            return None
        if state.status in {"completed", "failed", "cancelled", "paused"}:
            return state

        was_processing = state.status == "processing"
        state.status = "paused"
        state.current_step = "暂停中，当前片段完成后停止" if was_processing else "已暂停"
        state.error = ""
        state.touch()
        await self._persist_render_task_state(state=state)

        try:
            from app.workers.render_tasks import revoke_render_task

            revoke_render_task(task_id, terminate=False)
        except Exception as exc:
            logger.warning("Failed to pause render task %s: %s", task_id, exc)
        return state

    async def resume_render_task(
        self,
        task_id: str,
        *,
        user_id: str,
        auto_continue_segments: Optional[bool] = None,
    ) -> Optional[RenderTaskState]:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None or state.user_id != user_id:
            return None
        if state.status != "paused":
            raise RuntimeError("只有已暂停的任务才可以继续")

        if auto_continue_segments is not None:
            state.render_config["auto_continue_segments"] = bool(auto_continue_segments)
        state.status = "queued"
        state.current_step = "等待重新投递"
        state.error = ""
        state.final_output = {}
        state.touch()
        await self._persist_render_task_state(state=state)
        await self.start_render_task(task_id)
        return self.tasks.get(task_id) or await self._load_render_task_state(task_id)

    def _should_wait_for_clip_confirmation(
        self,
        *,
        state: RenderTaskState,
        completed_index: int,
        total_segments: int,
    ) -> bool:
        if bool(state.render_config.get("auto_continue_segments", False)):
            return False
        return completed_index < max(total_segments - 1, 0)

    async def retry_render_clip(
        self,
        task_id: str,
        *,
        clip_number: int,
        user_id: str,
    ) -> Optional[RenderTaskState]:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None or state.user_id != user_id:
            return None
        if state.status in {"processing", "queued", DISPATCHING_STATUS}:
            raise RuntimeError("请先暂停当前任务，再单独重生成片段")

        target_clip = next((clip for clip in state.clips if int(clip.clip_number) == int(clip_number)), None)
        if target_clip is None:
            raise RuntimeError(f"片段 {clip_number} 不存在")

        target_clip.status = "queued"
        target_clip.asset_url = ""
        target_clip.asset_type = ""
        target_clip.asset_filename = ""
        target_clip.provider = ""
        target_clip.error = ""
        state.final_output = {}
        state.status = "queued"
        state.current_step = "等待重新投递"
        state.error = ""
        state.touch()
        await self._persist_render_task_state(state=state)
        await self.start_render_task(task_id)
        return self.tasks.get(task_id) or await self._load_render_task_state(task_id)

    async def retry_render_task(self, task_id: str, *, user_id: str) -> Optional[RenderTaskState]:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None or state.user_id != user_id:
            return None
        if state.status not in {"failed", "cancelled"}:
            raise RuntimeError("只有失败或已取消的任务才可以重试")

        new_state = await self.create_render_task(
            user_id=state.user_id,
            project_id=state.project_id,
            project_title=state.project_title,
            segments=state.segments,
            keyframes=state.keyframes,
            character_profiles=state.character_profiles,
            scene_profiles=state.scene_profiles,
            render_config=state.render_config,
        )
        await self.start_render_task(new_state.task_id)
        return new_state

    async def get_render_task(self, task_id: str, *, user_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineRenderTask).where(
                    PipelineRenderTask.id == task_id,
                    PipelineRenderTask.user_id == user_id,
                )
            )
            task = result.scalar_one_or_none()

        if task is None:
            cached_state = self.tasks.get(task_id)
            if cached_state and cached_state.user_id == user_id:
                return cached_state.to_dict()
            return None

        refreshed_state = RenderTaskState(
            task_id=task.id,
            user_id=task.user_id,
            project_id=task.project_id or "",
            project_title=task.project_title or "未命名项目",
            segments=list(task.segments or []),
            keyframes=list(task.keyframes or []),
            character_profiles=list(task.character_profiles or []),
            scene_profiles=list(task.scene_profiles or []),
            render_config=dict(task.render_config or {}),
            status=task.status or "queued",
            progress=float(task.progress or 0.0),
            current_step=task.current_step or "等待开始",
            renderer=task.renderer or "pending",
            clips=[
                RenderedClip(**clip)
                for clip in (task.clips or [])
                if isinstance(clip, dict)
            ],
            final_output=dict(task.final_output or {}),
            fallback_used=bool(task.fallback_used),
            warnings=list(task.warnings or []),
            error=task.error or "",
            created_at=task.created_at.isoformat() if task.created_at else datetime.now().isoformat(),
            updated_at=task.updated_at.isoformat() if task.updated_at else datetime.now().isoformat(),
        )
        self.tasks[task_id] = refreshed_state
        return refreshed_state.to_dict()

    async def recover_interrupted_tasks(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            queued_result = await db.execute(
                select(PipelineRenderTask).where(
                    PipelineRenderTask.status == "queued"
                )
            )
            queued_tasks = queued_result.scalars().all()
            recoverable_queued_ids: List[str] = []
            for task in queued_tasks:
                current_step = str(task.current_step or "").strip()
                if current_step in RECOVERABLE_QUEUED_STEPS:
                    task.status = "paused"
                    task.current_step = "服务重启后已暂停，等待手动继续"
                    task.error = "服务启动时检测到任务未完成，已恢复为暂停状态"
                    task.updated_at = datetime.utcnow()
                    recoverable_queued_ids.append(task.id)

            dispatching_result = await db.execute(
                select(PipelineRenderTask).where(
                    PipelineRenderTask.status == DISPATCHING_STATUS
                )
            )
            dispatching_tasks = dispatching_result.scalars().all()
            recovered_dispatching_ids: List[str] = []
            for task in dispatching_tasks:
                task.status = "paused"
                task.current_step = "服务重启后已暂停，等待手动继续"
                task.error = "服务启动时检测到任务卡在入队阶段，已恢复为暂停状态"
                task.updated_at = datetime.utcnow()
                recovered_dispatching_ids.append(task.id)

            result = await db.execute(
                select(PipelineRenderTask).where(
                    PipelineRenderTask.status == "processing"
                )
            )
            processing_tasks = result.scalars().all()
            reset_processing_count = 0
            for task in processing_tasks:
                task.status = "paused"
                task.current_step = "任务中断，等待手动继续"
                task.error = "服务重启后已暂停，请手动继续"
                task.updated_at = datetime.utcnow()
                reset_processing_count += 1

            if recoverable_queued_ids or recovered_dispatching_ids or reset_processing_count:
                await db.commit()

        task_ids: List[str] = []
        for task_id in [*recoverable_queued_ids, *recovered_dispatching_ids, *[task.id for task in processing_tasks]]:
            if task_id not in task_ids:
                task_ids.append(task_id)
        return {
            "paused": len(task_ids),
            "requeued": len(task_ids),
            "reset_processing": reset_processing_count,
            "recovered_queued": len(recoverable_queued_ids),
            "recovered_dispatching": len(recovered_dispatching_ids),
            "task_ids": task_ids,
        }

    async def _claim_render_task_for_dispatch(self, task_id: str) -> Optional[RenderTaskState]:
        claimed_at = datetime.utcnow()
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(PipelineRenderTask)
                .where(
                    PipelineRenderTask.id == task_id,
                    PipelineRenderTask.status == "queued",
                    PipelineRenderTask.current_step.in_(list(CLAIMABLE_QUEUED_STEPS)),
                )
                .values(
                    status=DISPATCHING_STATUS,
                    current_step=DISPATCHING_STEP,
                    updated_at=claimed_at,
                )
            )
            if not result.rowcount:
                await db.rollback()
                return None
            await db.commit()

        claimed_state = await self._load_render_task_state(task_id)
        if claimed_state is not None:
            claimed_state.status = DISPATCHING_STATUS
            claimed_state.current_step = DISPATCHING_STEP
            claimed_state.updated_at = claimed_at.isoformat()
            self.tasks[task_id] = claimed_state
        return claimed_state

    async def _ensure_render_task_can_continue(
        self,
        task_id: str,
        state: Optional[RenderTaskState] = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineRenderTask.status, PipelineRenderTask.current_step).where(
                    PipelineRenderTask.id == task_id
                )
            )
            row = result.one_or_none()
        if row and row[0] == "cancelled":
            if state is not None:
                state.status = "cancelled"
                state.current_step = row[1] or "已取消"
            raise RenderTaskCancelledError(f"渲染任务已取消: {task_id}")
        if row and row[0] == "paused":
            if state is not None:
                state.status = "paused"
                state.current_step = row[1] or "已暂停"
            raise RenderTaskPausedError(f"渲染任务已暂停: {task_id}")

    def _mark_unfinished_clips_cancelled(self, state: RenderTaskState) -> None:
        for clip in state.clips:
            if clip.status not in {"completed", "failed", "cancelled"}:
                clip.status = "cancelled"

    def _mark_unfinished_clips_failed(self, state: RenderTaskState) -> None:
        for clip in state.clips:
            if clip.status not in {"completed", "failed", "cancelled"}:
                clip.status = "failed"

    async def mark_render_task_failed(
        self,
        task_id: str,
        *,
        error: str,
        current_step: str = "失败",
    ) -> Optional[RenderTaskState]:
        state = self.tasks.get(task_id)
        if state is None:
            state = await self._load_render_task_state(task_id)
        if state is None:
            return None
        if state.status in {"completed", "cancelled"}:
            return state

        state.status = "failed"
        state.error = error
        state.current_step = current_step
        self._mark_unfinished_clips_failed(state)
        state.touch()
        await self._persist_render_task_state(state=state)
        return state

    def format_full_script_text(self, script: FullScript) -> str:
        """将结构化剧本转换为可读、可编辑文本。"""
        lines: List[str] = [
            f"标题: {script.title}",
            f"简介: {script.synopsis}",
            f"基调: {script.tone}",
            f"主题: {', '.join(script.themes) if script.themes else '未设置'}",
            f"预估总时长: {script.total_duration:.1f} 秒",
            "",
            "【角色设定】",
        ]

        if script.characters:
            for index, character in enumerate(script.characters, start=1):
                lines.extend(
                    [
                        f"{index}. {character.name}",
                        f"  档案ID: {character.profile_id or '未绑定'}",
                        f"  档案版本: {character.profile_version}",
                        f"  定位: {character.role_type or '未设置'}",
                        f"  原型: {character.archetype or '未设置'}",
                        f"  外观: {character.appearance or '未设置'}",
                        f"  性格: {character.personality or '未设置'}",
                        f"  说话方式: {character.speaking_style or '未设置'}",
                        f"  常见动作: {character.common_actions or '未设置'}",
                        f"  当前情绪: {character.current_emotion or '未设置'}",
                        f"  表情: {character.facial_expression or '未设置'}",
                        f"  肢体语言: {character.body_language or '未设置'}",
                        f"  当前姿态: {character.current_pose or '未设置'}",
                        f"  必须保持: {', '.join(character.must_keep) if character.must_keep else '未设置'}",
                        f"  禁止偏离: {', '.join(character.forbidden) if character.forbidden else '未设置'}",
                        "",
                    ]
                )
        else:
            lines.extend(["暂无角色设定", ""])

        lines.append("【场景分解】")

        for scene in script.scenes:
            lines.extend(
                [
                    f"场景 {scene.scene_number}: {scene.title or '未命名场景'}",
                    f"场景档案ID: {scene.scene_profile_id or '未绑定'}",
                    f"场景档案版本: {scene.scene_profile_version}",
                    f"类型: {scene.scene_type or '未设置'}",
                    f"剧情功能: {scene.story_function or '未设置'}",
                    f"地点: {scene.location or '未设置'}",
                    f"地点细节: {scene.location_detail or '未设置'}",
                    f"时间: {scene.time or '未设置'}",
                    f"天气: {scene.weather or '未设置'}",
                    f"灯光: {scene.lighting or '未设置'}",
                    f"氛围: {scene.atmosphere or '未设置'}",
                    f"场景描述: {scene.description or '未设置'}",
                    f"必须元素: {', '.join(scene.must_have) if scene.must_have else '未设置'}",
                    f"禁止元素: {', '.join(scene.forbidden) if scene.forbidden else '未设置'}",
                ]
            )

            for shot in scene.shots:
                lines.extend(
                    [
                        "",
                        f"  镜头 {shot.shot_number} | 时长 {shot.duration:.1f} 秒",
                        f"  场景档案绑定: {shot.scene_profile_id or scene.scene_profile_id or '未绑定'} | 版本 {shot.scene_profile_version or scene.scene_profile_version}",
                        f"  角色档案绑定: {', '.join(shot.character_profile_ids) if shot.character_profile_ids else '无'}",
                        f"  镜头重点: {shot.prompt_focus or '未设置'}",
                        f"  景别: {shot.shot_type or '未设置'}",
                        f"  机位角度: {shot.camera_angle or '未设置'}",
                        f"  运动方式: {shot.camera_movement or '未设置'}",
                        f"  画面描述: {shot.description or '未设置'}",
                        f"  环境细节: {shot.environment or '未设置'}",
                        f"  光线: {shot.lighting or '未设置'}",
                        f"  出镜角色: {', '.join(shot.characters_in_shot) if shot.characters_in_shot else '无'}",
                    ]
                )

                if shot.actions:
                    lines.append("  动作:")
                    for action in shot.actions:
                        lines.append(f"    - {action.character}: {action.description}")

                if shot.dialogues:
                    lines.append("  对话:")
                    for dialogue in shot.dialogues:
                        label_parts = [part for part in [dialogue.emotion, dialogue.tone] if part]
                        label = f" [{' / '.join(label_parts)}]" if label_parts else ""
                        lines.append(f"    - {dialogue.speaker}{label}: {dialogue.text}")

                if shot.sound_effects:
                    lines.append(f"  音效: {', '.join(shot.sound_effects)}")
                if shot.music:
                    lines.append(f"  音乐: {shot.music}")

            lines.append("")

        return "\n".join(lines).strip()

    def _build_script_summary(self, script: FullScript) -> Dict[str, Any]:
        return {
            "title": script.title,
            "synopsis": script.synopsis,
            "total_duration": script.total_duration,
            "tone": script.tone,
            "themes": script.themes,
            "character_count": len(script.characters),
            "scene_count": len(script.scenes),
        }

    def _build_script_generation_input(
        self,
        *,
        user_input: str,
        style: str,
        target_total_duration: Optional[float],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        reference_images: List[Dict[str, Any]],
    ) -> str:
        lines = [user_input.strip()]
        if style:
            lines.append(f"视觉风格偏好: {style}")
        if target_total_duration:
            lines.append(
                f"目标总时长: {float(target_total_duration):.1f} 秒。"
                " 请让完整剧本中所有镜头时长之和尽量贴近该值，优先通过补足有效叙事镜头来满足时长。"
            )
        if character_profiles:
            lines.append("角色档案:")
            for index, profile in enumerate(character_profiles, start=1):
                lines.append(f"{index}. {self._build_character_profile_brief(profile)}")
        if scene_profiles:
            lines.append("场景档案:")
            for index, profile in enumerate(scene_profiles, start=1):
                lines.append(f"{index}. {self._build_scene_profile_brief(profile)}")
        if reference_images:
            lines.append(f"已上传参考图数量: {len(reference_images)}，请保持角色造型和场景风格与参考图一致。")
        return "\n".join(lines)

    def _build_character_profile_brief(self, profile: Dict[str, Any]) -> str:
        parts = [str(profile.get("name") or "未命名角色")]
        if profile.get("profile_version"):
            parts.append(f"版本: {profile['profile_version']}")
        if profile.get("category"):
            parts.append(f"分类: {profile['category']}")
        if profile.get("role"):
            parts.append(f"定位: {profile['role']}")
        if profile.get("archetype"):
            parts.append(f"原型: {profile['archetype']}")
        if profile.get("llm_summary"):
            parts.append(f"摘要: {profile['llm_summary']}")
        elif profile.get("description"):
            parts.append(f"设定: {profile['description']}")
        if profile.get("must_keep"):
            parts.append(f"必须保持: {', '.join(profile['must_keep'])}")
        if profile.get("forbidden_traits"):
            parts.append(f"禁止偏离: {', '.join(profile['forbidden_traits'])}")
        tags = profile.get("tags") or []
        if tags:
            parts.append(f"标签: {', '.join(tags)}")
        return "；".join(parts)

    def _build_scene_profile_brief(self, profile: Dict[str, Any]) -> str:
        parts = [str(profile.get("name") or "未命名场景")]
        if profile.get("profile_version"):
            parts.append(f"版本: {profile['profile_version']}")
        if profile.get("category"):
            parts.append(f"分类: {profile['category']}")
        if profile.get("scene_type"):
            parts.append(f"类型: {profile['scene_type']}")
        if profile.get("story_function"):
            parts.append(f"剧情功能: {profile['story_function']}")
        if profile.get("location"):
            parts.append(f"地点: {profile['location']}")
        if profile.get("time_setting"):
            parts.append(f"时间: {profile['time_setting']}")
        if profile.get("weather"):
            parts.append(f"天气: {profile['weather']}")
        if profile.get("lighting"):
            parts.append(f"灯光: {profile['lighting']}")
        if profile.get("llm_summary"):
            parts.append(f"摘要: {profile['llm_summary']}")
        elif profile.get("atmosphere"):
            parts.append(f"氛围: {profile['atmosphere']}")
        elif profile.get("description"):
            parts.append(f"设定: {profile['description']}")
        if profile.get("must_have_elements"):
            parts.append(f"必须元素: {', '.join(profile['must_have_elements'])}")
        if profile.get("forbidden_elements"):
            parts.append(f"禁止元素: {', '.join(profile['forbidden_elements'])}")
        tags = profile.get("tags") or []
        if tags:
            parts.append(f"标签: {', '.join(tags)}")
        return "；".join(parts)

    def _normalize_segment(self, segment: Dict[str, Any], index: int) -> Dict[str, Any]:
        """归一化前端传回的片段结构。"""
        duration = float(segment.get("duration") or 5.0)
        normalized_duration = max(1.0, min(duration, MAX_VIDEO_SEGMENT_DURATION))
        return {
            "segment_number": int(segment.get("segment_number") or index + 1),
            "title": str(segment.get("title") or f"片段 {index + 1}"),
            "description": str(segment.get("description") or ""),
            "start_time": float(segment.get("start_time") or 0.0),
            "end_time": float(segment.get("end_time") or 0.0),
            "duration": normalized_duration,
            "shots_summary": str(segment.get("shots_summary") or ""),
            "key_actions": list(segment.get("key_actions") or []),
            "key_dialogues": self._normalize_segment_dialogues(segment.get("key_dialogues") or []),
            "transition_in": str(segment.get("transition_in") or ""),
            "transition_out": str(segment.get("transition_out") or ""),
            "continuity_from_prev": str(segment.get("continuity_from_prev") or ""),
            "continuity_to_next": str(segment.get("continuity_to_next") or ""),
            "video_prompt": str(segment.get("video_prompt") or ""),
            "negative_prompt": str(segment.get("negative_prompt") or ""),
            "generation_config": dict(segment.get("generation_config") or {}),
            "scene_profile_id": str(segment.get("scene_profile_id") or ""),
            "scene_profile_version": int(segment.get("scene_profile_version") or 1),
            "character_profile_ids": list(segment.get("character_profile_ids") or []),
            "character_profile_versions": dict(segment.get("character_profile_versions") or {}),
            "prompt_focus": str(segment.get("prompt_focus") or ""),
            "contains_primary_character": bool(segment.get("contains_primary_character", False)),
            "ending_contains_primary_character": bool(segment.get("ending_contains_primary_character", False)),
            "pre_generate_start_frame": bool(segment.get("pre_generate_start_frame", False)),
            "start_frame_generation_reason": str(segment.get("start_frame_generation_reason") or ""),
            "prefer_primary_character_end_frame": bool(segment.get("prefer_primary_character_end_frame", False)),
            "new_character_profile_ids": list(segment.get("new_character_profile_ids") or []),
            "late_entry_character_profile_ids": list(segment.get("late_entry_character_profile_ids") or []),
            "handoff_character_profile_ids": list(segment.get("handoff_character_profile_ids") or []),
            "ending_contains_handoff_characters": bool(segment.get("ending_contains_handoff_characters", False)),
            "prefer_character_handoff_end_frame": bool(segment.get("prefer_character_handoff_end_frame", False)),
            "video_url": str(segment.get("video_url") or ""),
            "status": str(segment.get("status") or "ready"),
        }

    def _looks_like_character_id(self, value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{5,}", str(value or "").strip()))

    def _parse_segment_dialogue_text(self, raw_value: Any) -> Dict[str, str]:
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            return {}

        speaker_name = ""
        speaker_character_id = ""
        emotion = ""
        tone = ""
        text = raw_text

        prefix = ""
        content = ""
        for separator in ("：", ":"):
            if separator in raw_text:
                prefix, content = raw_text.split(separator, 1)
                break

        if prefix:
            bracket_values = re.findall(r"\[([^\]]+)\]", prefix)
            speaker_name = re.sub(r"\[[^\]]+\]", "", prefix).strip()
            text = content.strip()

            for item in bracket_values:
                normalized = str(item or "").strip()
                if not normalized:
                    continue
                if not speaker_character_id and self._looks_like_character_id(normalized):
                    speaker_character_id = normalized
                    continue

                labels = [part.strip() for part in re.split(r"\s*/\s*", normalized) if part.strip()]
                if labels and not emotion:
                    emotion = labels[0]
                if len(labels) >= 2 and not tone:
                    tone = labels[1]

        return {
            "text": text or raw_text,
            "speaker_name": speaker_name,
            "speaker_character_id": speaker_character_id,
            "emotion": emotion,
            "tone": tone,
        }

    def _normalize_segment_dialogues(self, value: Any) -> List[Dict[str, str]]:
        if isinstance(value, (str, dict)):
            iterable = [value]
        elif isinstance(value, (list, tuple)):
            iterable = list(value)
        else:
            iterable = []

        result: List[Dict[str, str]] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        for item in iterable:
            if isinstance(item, dict):
                normalized = {
                    "text": str(item.get("text") or item.get("dialogue") or "").strip(),
                    "speaker_name": str(item.get("speaker_name") or item.get("speaker") or "").strip(),
                    "speaker_character_id": str(item.get("speaker_character_id") or item.get("character_id") or "").strip(),
                    "emotion": str(item.get("emotion") or "").strip(),
                    "tone": str(item.get("tone") or "").strip(),
                }
            else:
                normalized = self._parse_segment_dialogue_text(item)

            if not normalized.get("text"):
                continue

            fingerprint = (
                normalized["text"],
                normalized["speaker_name"],
                normalized["speaker_character_id"],
                normalized["emotion"],
                normalized["tone"],
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(normalized)

        return result

    def _normalize_lookup_key(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).lower()

    def _resolve_segment_dialogue_bindings(
        self,
        dialogue_lines: List[Dict[str, str]],
        *,
        segment_characters: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        if not dialogue_lines:
            return []

        name_to_id: Dict[str, str] = {}
        for profile in segment_characters:
            profile_name = str(profile.get("name") or "").strip()
            profile_id = str(profile.get("id") or "").strip()
            if profile_name and profile_id:
                name_to_id[self._normalize_lookup_key(profile_name)] = profile_id

        resolved: List[Dict[str, str]] = []
        for item in dialogue_lines:
            normalized = {
                "text": str(item.get("text") or "").strip(),
                "speaker_name": str(item.get("speaker_name") or "").strip(),
                "speaker_character_id": str(item.get("speaker_character_id") or "").strip(),
                "emotion": str(item.get("emotion") or "").strip(),
                "tone": str(item.get("tone") or "").strip(),
            }
            if (
                not normalized["speaker_character_id"]
                and normalized["speaker_name"]
                and self._normalize_lookup_key(normalized["speaker_name"]) in name_to_id
            ):
                normalized["speaker_character_id"] = name_to_id[self._normalize_lookup_key(normalized["speaker_name"])]
            elif (
                not normalized["speaker_character_id"]
                and normalized["speaker_name"]
                and len(segment_characters) == 1
            ):
                normalized["speaker_character_id"] = str(segment_characters[0].get("id") or "").strip()
            resolved.append(normalized)

        return resolved

    def _dialogue_line_display_text(
        self,
        dialogue: Dict[str, Any],
        *,
        include_character_id: bool = True,
    ) -> str:
        text = str(dialogue.get("text") or "").strip()
        speaker_name = str(dialogue.get("speaker_name") or "").strip()
        speaker_character_id = str(dialogue.get("speaker_character_id") or "").strip()
        labels = [part for part in [str(dialogue.get("emotion") or "").strip(), str(dialogue.get("tone") or "").strip()] if part]

        prefix = speaker_name
        if include_character_id and speaker_character_id:
            prefix = f"{prefix} [{speaker_character_id}]".strip()
        if labels:
            prefix = f"{prefix} [{' / '.join(labels)}]".strip()

        if prefix and text:
            return f"{prefix}: {text}"
        return text or prefix

    async def _persist_render_task_state(
        self,
        *,
        state: RenderTaskState,
        user_id: Optional[str] = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineRenderTask).where(PipelineRenderTask.id == state.task_id)
            )
            record = result.scalar_one_or_none()

            if record is None:
                if not user_id:
                    raise ValueError(f"创建渲染任务记录时缺少 user_id: {state.task_id}")
                record = PipelineRenderTask(
                    id=state.task_id,
                    user_id=user_id,
                    project_id=state.project_id or None,
                    project_title=state.project_title,
                    segments=state.segments,
                    keyframes=state.keyframes,
                    character_profiles=state.character_profiles,
                    scene_profiles=state.scene_profiles,
                    render_config=state.render_config,
                    clips=[asdict(clip) for clip in state.clips],
                    final_output=state.final_output,
                    fallback_used=state.fallback_used,
                    warnings=state.warnings,
                    status=state.status,
                    progress=state.progress,
                    current_step=state.current_step,
                    renderer=state.renderer,
                    error=state.error or None,
                    created_at=datetime.fromisoformat(state.created_at) if state.created_at else datetime.utcnow(),
                    updated_at=datetime.fromisoformat(state.updated_at) if state.updated_at else datetime.utcnow(),
                )
                db.add(record)
            else:
                record.project_id = state.project_id or None
                record.project_title = state.project_title
                record.segments = state.segments
                record.keyframes = state.keyframes
                record.character_profiles = state.character_profiles
                record.scene_profiles = state.scene_profiles
                record.render_config = state.render_config
                record.status = state.status
                record.progress = state.progress
                record.current_step = state.current_step
                record.renderer = state.renderer
                record.clips = [asdict(clip) for clip in state.clips]
                record.final_output = state.final_output
                record.fallback_used = state.fallback_used
                record.warnings = state.warnings
                record.error = state.error or None
                record.updated_at = datetime.fromisoformat(state.updated_at) if state.updated_at else datetime.utcnow()

            if state.project_id:
                await self._sync_project_render_status(
                    db=db,
                    user_id=user_id or record.user_id,
                    project_id=state.project_id,
                    task_id=state.task_id,
                    status=state.status,
                )
            await db.commit()

    async def _load_render_task_state(self, task_id: str) -> Optional[RenderTaskState]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineRenderTask).where(PipelineRenderTask.id == task_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            state = RenderTaskState(
                task_id=record.id,
                user_id=record.user_id,
                project_id=record.project_id or "",
                project_title=record.project_title or "未命名项目",
                segments=list(record.segments or []),
                keyframes=list(record.keyframes or []),
                character_profiles=list(record.character_profiles or []),
                scene_profiles=list(record.scene_profiles or []),
                render_config=dict(record.render_config or {}),
                status=record.status or "queued",
                progress=float(record.progress or 0.0),
                current_step=record.current_step or "等待开始",
                renderer=record.renderer or "pending",
                clips=[
                    RenderedClip(**clip)
                    for clip in (record.clips or [])
                    if isinstance(clip, dict)
                ],
                final_output=dict(record.final_output or {}),
                fallback_used=bool(record.fallback_used),
                warnings=list(record.warnings or []),
                error=record.error or "",
                created_at=record.created_at.isoformat() if record.created_at else datetime.now().isoformat(),
                updated_at=record.updated_at.isoformat() if record.updated_at else datetime.now().isoformat(),
            )
        self.tasks[task_id] = state
        return state

    async def _sync_project_render_status(
        self,
        *,
        db: Any,
        user_id: str,
        project_id: str,
        task_id: str,
        status: str,
    ) -> None:
        result = await db.execute(
            select(PipelineProject).where(
                PipelineProject.id == project_id,
                PipelineProject.user_id == user_id,
                PipelineProject.deleted_at.is_(None),
            )
        )
        project = result.scalar_one_or_none()
        if project is None:
            return

        project.last_render_task_id = task_id or None
        if status in {"queued", "processing", DISPATCHING_STATUS}:
            project.status = "in_progress"
        elif status == "paused":
            project.status = "paused"
        elif status == "completed":
            project.status = "completed"
        elif status == "failed":
            project.status = "failed"
        elif status == "cancelled":
            project.status = "cancelled"
        project.updated_at = datetime.utcnow()

    def _normalize_reference_image(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        return {
            "id": str(reference.get("id") or reference.get("filename") or uuid.uuid4().hex),
            "url": str(reference.get("url") or ""),
            "filename": str(reference.get("filename") or f"reference_{index + 1}.png"),
            "original_filename": str(reference.get("original_filename") or reference.get("filename") or f"reference_{index + 1}.png"),
            "content_type": str(reference.get("content_type") or "image/png"),
            "size": int(reference.get("size") or 0),
            "source": str(reference.get("source") or "upload"),
        }

    def _normalize_keyframe_bundle(self, bundle: Dict[str, Any], index: int) -> Dict[str, Any]:
        return {
            "segment_number": int(bundle.get("segment_number") or index + 1),
            "title": str(bundle.get("title") or f"片段 {index + 1}"),
            "start_frame": dict(bundle.get("start_frame") or {}),
            "end_frame": dict(bundle.get("end_frame") or {}),
            "continuity_notes": str(bundle.get("continuity_notes") or ""),
            "status": str(bundle.get("status") or "ready"),
        }

    async def _generate_keyframe_asset(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        frame_kind: str,
        style: str,
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        reference_images: List[Dict[str, Any]],
        base_asset: Optional[KeyframeAsset],
    ) -> KeyframeAsset:
        keyframe_reference_images = self._build_keyframe_reference_images(
            task_dir=task_dir,
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
            reference_images=reference_images,
        )
        if keyframe_reference_images:
            logger.info(
                "Keyframe reference images for segment %s frame=%s: %s",
                segment.get("segment_number"),
                frame_kind,
                ", ".join(
                    str(item.get("label") or item.get("anchor_type") or item.get("filename") or "").strip()
                    for item in keyframe_reference_images
                    if str(item.get("url") or "").strip()
                ) or "none",
            )
        prompt = self._build_keyframe_prompt(
            segment=segment,
            frame_kind=frame_kind,
            style=style,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
            reference_images=keyframe_reference_images,
        )

        segment_characters, _ = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        logger.info(
            "Image keyframe prompt for segment %s frame=%s characters=%s:\n%s",
            segment.get("segment_number"),
            frame_kind,
            ", ".join(
                str(item.get("name") or item.get("id") or "").strip()
                for item in segment_characters
                if str(item.get("name") or item.get("id") or "").strip()
            ) or "none",
            prompt,
        )
        generated = await asyncio.to_thread(
            self._generate_keyframe_with_preferred_provider,
            task_dir,
            segment,
            frame_kind,
            prompt,
            keyframe_reference_images,
            base_asset,
        )
        if generated:
            return generated

        logger.warning(
            "Image keyframe generation returned no asset for segment=%s frame=%s, fallback to placeholder",
            segment["segment_number"],
            frame_kind,
        )

        return self._generate_keyframe_placeholder(
            task_dir=task_dir,
            segment=segment,
            frame_kind=frame_kind,
            prompt=prompt,
            base_asset=base_asset,
        )

    def _generate_keyframe_with_preferred_provider(
        self,
        task_dir: Path,
        segment: Dict[str, Any],
        frame_kind: str,
        prompt: str,
        reference_images: List[Dict[str, Any]],
        base_asset: Optional[KeyframeAsset],
    ) -> Optional[KeyframeAsset]:
        try:
            reference_paths = self._existing_reference_paths(reference_images)
            base_path = self._asset_url_to_path(base_asset.asset_url) if base_asset else None

            if base_path and base_path.exists():
                logger.info(
                    "Preferred image keyframe mode=image_to_image segment=%s frame=%s base=%s references=%s",
                    segment.get("segment_number"),
                    frame_kind,
                    base_path.name,
                    len(reference_paths),
                )
                result = self.image_generator.generate_image_to_image(
                    str(base_path),
                    prompt,
                    aspect_ratio="16:9",
                    image_size="2k",
                )
            elif len(reference_paths) > 1:
                logger.info(
                    "Preferred image keyframe mode=multi_image_mix segment=%s frame=%s references=%s",
                    segment.get("segment_number"),
                    frame_kind,
                    ", ".join(path.name for path in reference_paths),
                )
                result = self.image_generator.generate_multi_image_mix(
                    [str(path) for path in reference_paths],
                    prompt,
                    aspect_ratio="16:9",
                    image_size="2k",
                )
            elif len(reference_paths) == 1:
                logger.info(
                    "Preferred image keyframe mode=image_to_image segment=%s frame=%s reference=%s",
                    segment.get("segment_number"),
                    frame_kind,
                    reference_paths[0].name,
                )
                result = self.image_generator.generate_image_to_image(
                    str(reference_paths[0]),
                    prompt,
                    aspect_ratio="16:9",
                    image_size="2k",
                )
            else:
                logger.info(
                    "Preferred image keyframe mode=text_to_image segment=%s frame=%s",
                    segment.get("segment_number"),
                    frame_kind,
                )
                result = self.image_generator.generate_text_to_image(
                    prompt,
                    aspect_ratio="16:9",
                    image_size="2k",
                )

            if not result.get("success") or not result.get("image_data"):
                logger.warning("Preferred image keyframe generation failed: %s", result.get("error"))
                return None

            return self._store_binary_image(
                task_dir=task_dir,
                filename=f"segment_{segment['segment_number']:02d}_{frame_kind}.png",
                content=result["image_data"],
                prompt=prompt,
                source=str(result.get("source") or "image-provider-keyframe"),
            )
        except Exception as exc:
            logger.warning("Preferred image generation unavailable, fallback to placeholder: %s", exc)
            return None

    def _generate_keyframe_placeholder(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        frame_kind: str,
        prompt: str,
        base_asset: Optional[KeyframeAsset],
    ) -> KeyframeAsset:
        try:
            from PIL import Image, ImageDraw, ImageFont

            width, height = 1280, 720
            colors = {
                "start": (18, 48, 74),
                "end": (72, 34, 60),
            }
            background = colors.get(frame_kind, (20, 20, 20))
            image = Image.new("RGB", (width, height), background)
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()

            draw.rectangle((40, 36, width - 40, height - 36), outline=(255, 255, 255), width=3)
            draw.text((72, 72), f"{segment['title']} | {frame_kind.upper()} FRAME", fill=(255, 200, 90), font=font)
            draw.text((72, 112), f"Clip {segment['segment_number']:02d} | {segment['duration']:.1f}s", fill=(255, 255, 255), font=font)

            y = 180
            for line in self._wrap_lines(segment["description"] or segment["shots_summary"] or "暂无片段描述", width=62)[:8]:
                draw.text((72, y), line, fill=(245, 245, 245), font=font)
                y += 28

            y += 12
            draw.text((72, y), "Prompt", fill=(255, 200, 90), font=font)
            y += 28
            for line in self._wrap_lines(prompt, width=62)[:7]:
                draw.text((72, y), line, fill=(220, 220, 220), font=font)
                y += 24

            if base_asset:
                draw.text((72, height - 110), f"Base reference: {base_asset.asset_filename}", fill=(245, 245, 245), font=font)
            draw.text((72, height - 78), "Local placeholder keyframe", fill=(245, 245, 245), font=font)

            filename = f"segment_{segment['segment_number']:02d}_{frame_kind}.png"
            output_path = task_dir / filename
            image.save(output_path, format="PNG")

            return KeyframeAsset(
                asset_url=self._build_asset_url(output_path),
                thumbnail_url="",
                asset_type="image/png",
                asset_filename=filename,
                prompt=prompt,
                source="local-placeholder",
                status="completed",
                notes="本地占位关键帧，用于开发联调",
            )
        except Exception as exc:
            logger.warning("PNG keyframe placeholder failed, fallback to SVG: %s", exc)
            filename = f"segment_{segment['segment_number']:02d}_{frame_kind}.svg"
            output_path = task_dir / filename
            output_path.write_text(
                f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <rect width="1280" height="720" fill="#14213d"/>
  <rect x="40" y="36" width="1200" height="648" fill="none" stroke="#ffffff" stroke-width="3"/>
  <text x="72" y="84" fill="#ffc857" font-size="28" font-family="monospace">{escape(segment['title'][:72])} | {frame_kind.upper()} FRAME</text>
  <foreignObject x="72" y="140" width="1120" height="220"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#f5f5f5;font-size:20px;line-height:1.5;font-family:monospace;white-space:pre-wrap;">{html.escape((segment['description'] or segment['shots_summary'] or '')[:420])}</div></foreignObject>
  <foreignObject x="72" y="380" width="1120" height="220"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#d9d9d9;font-size:18px;line-height:1.5;font-family:monospace;white-space:pre-wrap;">{html.escape(prompt[:520])}</div></foreignObject>
</svg>
""",
                encoding="utf-8",
            )
            return KeyframeAsset(
                asset_url=self._build_asset_url(output_path),
                thumbnail_url="",
                asset_type="image/svg+xml",
                asset_filename=filename,
                prompt=prompt,
                source="local-placeholder",
                status="completed",
                notes="本地占位关键帧，用于开发联调",
            )

    def _store_binary_image(
        self,
        *,
        task_dir: Path,
        filename: str,
        content: bytes,
        prompt: str,
        source: str,
    ) -> KeyframeAsset:
        output_path = task_dir / filename
        output_path.write_bytes(content)
        thumbnail_path = ensure_thumbnail_for_path(output_path)
        return KeyframeAsset(
            asset_url=self._build_asset_url(output_path),
            thumbnail_url=build_upload_url(thumbnail_path) if thumbnail_path else "",
            asset_type="image/png",
            asset_filename=filename,
            prompt=prompt,
            source=source,
            status="completed",
        )

    def _build_keyframe_prompt(
        self,
        *,
        segment: Dict[str, Any],
        frame_kind: str,
        style: str,
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        reference_images: List[Dict[str, Any]],
    ) -> str:
        segment_characters, segment_scene = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        character_text = ""
        if segment_characters:
            character_text = "Character identity anchors: " + " | ".join(
                self._build_character_image_base(profile) for profile in segment_characters
            ) + ". "
        scene_text = ""
        if segment_scene:
            scene_text = f"Scene base: {self._build_scene_image_base(segment_scene)}. "
        style_text = f"Visual style: {style}. " if style else ""
        reference_text = (
            f"Reference anchors provided: {self._describe_reference_images(reference_images)}. "
            "Keep subject appearance, face identity, costume structure, environment layout, lighting mood, and spatial atmosphere consistent with these anchor images. "
            if reference_images
            else ""
        )
        frame_goal = "opening shot, establish pose, camera-ready composition" if frame_kind == "start" else "ending shot, preserve continuity, prepare next segment entry"
        prompt_focus = str(segment.get("prompt_focus") or "")
        continuity_text = str(segment.get("continuity_to_next") if frame_kind == "end" else segment.get("continuity_from_prev") or "")
        hard_constraints = self._build_segment_hard_constraints(segment_characters, segment_scene)
        stable_visual_base = self._build_segment_image_prompt_base(segment_characters, segment_scene)
        start_frame_extra = ""
        if frame_kind == "start" and str(segment.get("start_frame_generation_reason") or "") == "new_character_entry":
            start_frame_extra = (
                "This frame is a new character's first formal entrance. "
                "Compose the newly entering character prominently, make face, hairstyle, outfit, silhouette, and color palette exceptionally clear, and prioritize identity stability over spectacle. "
            )
        return (
            f"{character_text}{scene_text}{style_text}{reference_text}"
            f"{f'Stable visual base: {stable_visual_base}. ' if stable_visual_base else ''}"
            f"{segment['video_prompt'] or segment['description']}. "
            f"{f'Key focus: {prompt_focus}. ' if prompt_focus else ''}"
            f"{f'Continuity note: {continuity_text}. ' if continuity_text else ''}"
            f"{hard_constraints}"
            f"{start_frame_extra}"
            f"Generate a {frame_goal} keyframe for clip {segment['segment_number']}, "
            f"cinematic, coherent subject identity, clear feature details, spatially accurate environment, 16:9 composition."
        ).strip()

    def _resolve_character_profiles(
        self,
        *,
        selected_character_ids: List[str],
        character_profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        resolved: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for index, profile in enumerate(character_profiles):
            normalized = self._normalize_character_profile(profile, index)
            profile_key = normalized["id"] or normalized["name"]
            if profile_key and profile_key not in seen:
                resolved.append(normalized)
                seen.add(profile_key)

        return resolved

    def _resolve_scene_profiles(
        self,
        *,
        selected_scene_ids: List[str],
        scene_profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        resolved: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for index, profile in enumerate(scene_profiles):
            normalized = self._normalize_scene_profile(profile, index)
            profile_key = normalized["id"] or normalized["name"]
            if profile_key and profile_key not in seen:
                resolved.append(normalized)
                seen.add(profile_key)

        return resolved

    def _normalize_character_profile(self, profile: Dict[str, Any], index: int) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        raw_tags = profile.get("tags") or []
        if isinstance(raw_tags, str):
            tags = [item.strip() for item in raw_tags.replace("，", ",").split(",") if item.strip()]
        else:
            tags = [str(item).strip() for item in raw_tags if str(item).strip()]

        normalized = {
            "id": str(profile.get("id") or ""),
            "name": str(profile.get("name") or f"角色{index + 1}").strip(),
            "category": str(profile.get("category") or "").strip(),
            "role": str(profile.get("role") or "").strip(),
            "archetype": str(profile.get("archetype") or "").strip(),
            "age_range": str(profile.get("age_range") or "").strip(),
            "gender_presentation": str(profile.get("gender_presentation") or "").strip(),
            "description": str(profile.get("description") or "").strip(),
            "appearance": str(profile.get("appearance") or "").strip(),
            "personality": str(profile.get("personality") or "").strip(),
            "core_appearance": str(profile.get("core_appearance") or "").strip(),
            "hair": str(profile.get("hair") or "").strip(),
            "face_features": str(profile.get("face_features") or "").strip(),
            "body_shape": str(profile.get("body_shape") or "").strip(),
            "outfit": str(profile.get("outfit") or "").strip(),
            "gear": str(profile.get("gear") or "").strip(),
            "color_palette": str(profile.get("color_palette") or "").strip(),
            "visual_do_not_change": str(profile.get("visual_do_not_change") or "").strip(),
            "speaking_style": str(profile.get("speaking_style") or "").strip(),
            "common_actions": str(profile.get("common_actions") or "").strip(),
            "emotion_baseline": str(profile.get("emotion_baseline") or "").strip(),
            "voice_description": self._normalize_voice_description(profile.get("voice_description") or ""),
            "forbidden_behaviors": str(profile.get("forbidden_behaviors") or "").strip(),
            "prompt_hint": str(profile.get("prompt_hint") or "").strip(),
            "llm_summary": str(profile.get("llm_summary") or "").strip(),
            "image_prompt_base": str(profile.get("image_prompt_base") or "").strip(),
            "video_prompt_base": str(profile.get("video_prompt_base") or "").strip(),
            "negative_prompt": str(profile.get("negative_prompt") or "").strip(),
            "tags": tags,
            "must_keep": list(profile.get("must_keep") or []),
            "forbidden_traits": list(profile.get("forbidden_traits") or []),
            "aliases": list(profile.get("aliases") or []),
            "profile_version": int(profile.get("profile_version") or 1),
            "source": str(profile.get("source") or "request"),
            "reference_image_url": str(profile.get("reference_image_url") or "").strip(),
            "reference_image_original_name": str(profile.get("reference_image_original_name") or "").strip(),
            "three_view_image_url": str(profile.get("three_view_image_url") or "").strip(),
            "three_view_prompt": str(profile.get("three_view_prompt") or "").strip(),
            "face_closeup_image_url": str(profile.get("face_closeup_image_url") or "").strip(),
            "created_at": str(profile.get("created_at") or now),
            "updated_at": str(profile.get("updated_at") or profile.get("created_at") or now),
        }
        normalized["display_image_url"] = normalized["reference_image_url"]
        normalized["identity_reference_images"] = self._build_character_identity_reference_images(normalized)
        normalized["identity_anchor_pack"] = self._build_character_identity_anchor_pack(normalized)
        return normalized

    def _normalize_scene_profile(self, profile: Dict[str, Any], index: int) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        raw_tags = profile.get("tags") or []
        if isinstance(raw_tags, str):
            tags = [item.strip() for item in raw_tags.replace("，", ",").split(",") if item.strip()]
        else:
            tags = [str(item).strip() for item in raw_tags if str(item).strip()]

        return {
            "id": str(profile.get("id") or ""),
            "name": str(profile.get("name") or f"场景{index + 1}").strip(),
            "category": str(profile.get("category") or "").strip(),
            "scene_type": str(profile.get("scene_type") or "").strip(),
            "description": str(profile.get("description") or "").strip(),
            "story_function": str(profile.get("story_function") or "").strip(),
            "location": str(profile.get("location") or "").strip(),
            "scene_rules": str(profile.get("scene_rules") or "").strip(),
            "time_setting": str(profile.get("time_setting") or "").strip(),
            "weather": str(profile.get("weather") or "").strip(),
            "lighting": str(profile.get("lighting") or "").strip(),
            "atmosphere": str(profile.get("atmosphere") or "").strip(),
            "architecture_style": str(profile.get("architecture_style") or "").strip(),
            "color_palette": str(profile.get("color_palette") or "").strip(),
            "prompt_hint": str(profile.get("prompt_hint") or "").strip(),
            "llm_summary": str(profile.get("llm_summary") or "").strip(),
            "image_prompt_base": str(profile.get("image_prompt_base") or "").strip(),
            "video_prompt_base": str(profile.get("video_prompt_base") or "").strip(),
            "negative_prompt": str(profile.get("negative_prompt") or "").strip(),
            "tags": tags,
            "allowed_characters": list(profile.get("allowed_characters") or []),
            "props_must_have": list(profile.get("props_must_have") or []),
            "props_forbidden": list(profile.get("props_forbidden") or []),
            "must_have_elements": list(profile.get("must_have_elements") or []),
            "forbidden_elements": list(profile.get("forbidden_elements") or []),
            "camera_preferences": list(profile.get("camera_preferences") or []),
            "profile_version": int(profile.get("profile_version") or 1),
            "source": str(profile.get("source") or "request"),
            "reference_image_url": str(profile.get("reference_image_url") or "").strip(),
            "reference_image_original_name": str(profile.get("reference_image_original_name") or "").strip(),
            "created_at": str(profile.get("created_at") or now),
            "updated_at": str(profile.get("updated_at") or profile.get("created_at") or now),
        }

    def _existing_reference_paths(self, reference_images: List[Dict[str, Any]]) -> List[Path]:
        paths: List[Path] = []
        for reference in reference_images:
            reference_path = self._asset_url_to_path(reference.get("url", ""))
            if reference_path and reference_path.exists():
                paths.append(reference_path)
        return paths

    def _choose_render_provider(self, render_config: Dict[str, Any]) -> str:
        requested = render_config.get("provider", "auto")
        if requested == "local":
            return "local-preview"
        if requested == "kling":
            if self._kling_enabled():
                return "kling-official"
            require_kling_credentials(action_label="调用可灵视频生成；或改用自动选择 / 豆包 / local 预览模式")
        if requested == "doubao":
            if self._doubao_enabled():
                return "doubao-official"
            require_doubao_api_key(action_label="调用豆包视频生成；或显式选择 local 预览模式")
        if requested == "auto":
            if self._kling_enabled():
                return "kling-official"
            if self._doubao_enabled():
                return "doubao-official"
            require_kling_credentials(action_label="调用可灵视频生成；当前未命中可灵配置，也未找到豆包视频配置")
        raise RuntimeError(f"不支持的视频 provider: {requested}")

    async def _render_video_or_preview(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Dict[str, Any],
    ) -> Dict[str, str]:
        provider = self._choose_render_provider(render_config)
        if provider == "kling-official":
            try:
                rendered = await self._try_render_kling_video(
                    task_dir=task_dir,
                    segment=segment,
                    keyframe_bundle=keyframe_bundle,
                    character_profiles=character_profiles,
                    scene_profiles=scene_profiles,
                    render_config=render_config,
                )
                if rendered:
                    return rendered
                raise RuntimeError(f"片段 {segment['segment_number']} 可灵视频生成失败，未获得真实视频结果")
            except Exception as exc:
                if str(render_config.get("provider") or "auto") == "auto" and self._doubao_enabled():
                    logger.warning(
                        "Kling render failed for segment %s under auto mode, fallback to Doubao: %s",
                        segment.get("segment_number"),
                        exc,
                    )
                    rendered = await self._try_render_doubao_video(
                        task_dir=task_dir,
                        segment=segment,
                        keyframe_bundle=keyframe_bundle,
                        character_profiles=character_profiles,
                        scene_profiles=scene_profiles,
                        render_config=render_config,
                    )
                    if rendered:
                        return rendered
                raise
        if provider == "doubao-official":
            rendered = await self._try_render_doubao_video(
                task_dir=task_dir,
                segment=segment,
                keyframe_bundle=keyframe_bundle,
                character_profiles=character_profiles,
                scene_profiles=scene_profiles,
                render_config=render_config,
            )
            if rendered:
                return rendered
            raise RuntimeError(f"片段 {segment['segment_number']} 视频生成失败，未获得真实视频结果")

        if provider != "local-preview":
            raise RuntimeError(f"不支持的渲染 provider: {provider}")

        preview_renderer = "gif"
        if preview_renderer == "gif":
            try:
                return self._render_segment_gif(
                    task_dir=task_dir,
                    segment=segment,
                    keyframe_bundle=keyframe_bundle,
                )
            except Exception as exc:
                logger.warning("GIF preview render failed, fallback to SVG: %s", exc)

        return self._render_segment_svg(
            task_dir=task_dir,
            segment=segment,
            keyframe_bundle=keyframe_bundle,
        )

    async def _try_render_doubao_video(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        if not self._doubao_enabled():
            require_doubao_api_key(action_label="调用豆包视频生成")

        try:
            from app.services.doubao_video_official import (
                DoubaoVideoGenerator,
                SEEDANCE_15_PRO,
            )

            generator = DoubaoVideoGenerator(
                api_key=self._get_doubao_api_key(),
                model=str(render_config.get("provider_model") or settings.DOUBAO_VIDEO_MODEL or SEEDANCE_15_PRO),
                base_url=settings.DOUBAO_BASE_URL,
            )

            used_text_only_retry = False
            used_sanitized_text_retry = False
            response = None
            try:
                request_kwargs = {
                    "ratio": self._normalize_doubao_aspect_ratio(render_config.get("aspect_ratio", "16:9")),
                    "resolution": self._normalize_doubao_resolution(render_config.get("resolution", "720p")),
                    "seed": self._normalize_provider_seed(render_config.get("seed")),
                    "watermark": bool(render_config.get("watermark", False)),
                    "camera_fixed": bool(render_config.get("camera_fixed", False)),
                    "generate_audio": bool(render_config.get("generate_audio", True)),
                    "return_last_frame": True,
                    "service_tier": str(render_config.get("service_tier") or "default"),
                }
                primary_content = self._build_doubao_content(
                    task_dir=task_dir,
                    segment=segment,
                    keyframe_bundle=keyframe_bundle,
                    character_profiles=character_profiles,
                    scene_profiles=scene_profiles,
                    render_config=render_config,
                )
                request_kwargs["duration"] = self._normalize_doubao_duration(
                    duration=segment["duration"],
                    model_name=str(render_config.get("provider_model") or settings.DOUBAO_VIDEO_MODEL or ""),
                    content=primary_content,
                )
                try:
                    response = await generator.create_video_task(
                        content=primary_content,
                        **request_kwargs,
                    )
                except httpx.HTTPStatusError as exc:
                    if self._is_sensitive_image_error(exc):
                        used_text_only_retry = True
                        logger.warning(
                            "Doubao rejected reference image for segment %s, retrying with text-only prompt",
                            segment.get("segment_number"),
                        )
                        text_only_content = self._build_doubao_content(
                            task_dir=task_dir,
                            segment=segment,
                            keyframe_bundle=None,
                            character_profiles=character_profiles,
                            scene_profiles=scene_profiles,
                            render_config=render_config,
                        )
                        try:
                            response = await generator.create_video_task(
                                content=text_only_content,
                                **request_kwargs,
                            )
                        except httpx.HTTPStatusError as retry_exc:
                            if self._is_sensitive_text_error(retry_exc):
                                used_sanitized_text_retry = True
                                logger.warning(
                                    "Doubao rejected text-only prompt for segment %s, retrying with sanitized text-only prompt",
                                    segment.get("segment_number"),
                                )
                                sanitized_text_only_content = self._sanitize_doubao_content_for_retry(
                                    content=text_only_content,
                                    segment=segment,
                                )
                                response = await generator.create_video_task(
                                    content=sanitized_text_only_content,
                                    **request_kwargs,
                                )
                            else:
                                raise
                    elif self._is_sensitive_text_error(exc):
                        used_sanitized_text_retry = True
                        logger.warning(
                            "Doubao rejected prompt text for segment %s, retrying with sanitized prompt",
                            segment.get("segment_number"),
                        )
                        sanitized_content = self._sanitize_doubao_content_for_retry(
                            content=primary_content,
                            segment=segment,
                        )
                        response = await generator.create_video_task(
                            content=sanitized_content,
                            **request_kwargs,
                        )
                    else:
                        raise
                if response is None:
                    raise RuntimeError(f"片段 {segment['segment_number']} 未获得豆包视频任务响应")
                if response.status in {"pending", "processing", "queued", "running"}:
                    response = await generator.wait_for_completion(response.id, poll_interval=5, max_wait_time=900)
            finally:
                await generator.close()

            if response.video_url:
                asset_filename = f"clip_{segment['segment_number']:02d}.mp4"
                provider = "doubao-official"
                if used_text_only_retry and used_sanitized_text_retry:
                    provider = "doubao-official-text-only-sanitized"
                elif used_text_only_retry:
                    provider = "doubao-official-text-only"
                elif used_sanitized_text_retry:
                    provider = "doubao-official-sanitized"
                return {
                    "asset_url": response.video_url,
                    "asset_type": "video/mp4",
                    "asset_filename": asset_filename,
                    "provider": provider,
                    "last_frame_url": response.last_frame_url or "",
                }
            raise RuntimeError(f"片段 {segment['segment_number']} 未返回 video_url")
        except Exception as exc:
            logger.error("Doubao render failed for segment %s: %s", segment.get("segment_number"), exc)
            raise RuntimeError(f"片段 {segment['segment_number']} 豆包视频生成失败: {exc}") from exc

    async def _try_render_kling_video(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        if not self._kling_enabled():
            require_kling_credentials(action_label="调用可灵视频生成")

        try:
            from app.services.kling_video import KlingVideoGenerator

            access_key, secret_key = require_kling_credentials(action_label="调用可灵视频生成")
            generator = KlingVideoGenerator(
                access_key=access_key,
                secret_key=secret_key,
                model=self._resolve_kling_model(str(render_config.get("provider_model") or "")),
                mode=self._resolve_kling_mode(),
                base_url=settings.KLING_BASE_URL,
            )

            try:
                image_list = self._build_kling_image_list(
                    task_dir=task_dir,
                    segment=segment,
                    keyframe_bundle=keyframe_bundle,
                    character_profiles=character_profiles,
                    scene_profiles=scene_profiles,
                )
                if not image_list:
                    raise RuntimeError("可灵 multi-image2video 缺少可用图片输入")

                prompt = self._build_segment_video_prompt(
                    segment=segment,
                    character_profiles=character_profiles,
                    scene_profiles=scene_profiles,
                )
                negative_prompt = self._build_segment_negative_prompt(
                    segment=segment,
                    character_profiles=character_profiles,
                    scene_profiles=scene_profiles,
                )

                response = await generator.create_multi_image_video_task(
                    image_list=image_list,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    duration=self._normalize_kling_duration(segment["duration"]),
                    aspect_ratio=self._normalize_kling_aspect_ratio(str(render_config.get("aspect_ratio") or "16:9")),
                    enable_audio=bool(render_config.get("generate_audio", True)),
                    external_task_id=f"segment-{segment.get('segment_number')}",
                )
                if response.status.lower() in {"submitted", "processing", "queued", "running"}:
                    response = await generator.wait_for_completion(
                        response.task_id,
                        poll_interval=5,
                        max_wait_time=900,
                    )
            finally:
                await generator.close()

            if response.video_url:
                return {
                    "asset_url": response.video_url,
                    "asset_type": "video/mp4",
                    "asset_filename": f"clip_{segment['segment_number']:02d}.mp4",
                    "provider": "kling-official",
                    "last_frame_url": "",
                }
            raise RuntimeError(response.error_message or f"片段 {segment['segment_number']} 未返回 video_url")
        except Exception as exc:
            logger.error("Kling render failed for segment %s: %s", segment.get("segment_number"), exc)
            raise RuntimeError(f"片段 {segment['segment_number']} 可灵视频生成失败: {exc}") from exc

    def _is_sensitive_image_error(self, exc: Exception) -> bool:
        if not isinstance(exc, httpx.HTTPStatusError) or exc.response is None:
            return False
        try:
            payload = exc.response.json()
        except Exception:
            return False
        error = payload.get("error") or {}
        return error.get("code") == "InputImageSensitiveContentDetected"

    def _is_sensitive_text_error(self, exc: Exception) -> bool:
        if not isinstance(exc, httpx.HTTPStatusError) or exc.response is None:
            return False
        try:
            payload = exc.response.json()
        except Exception:
            return False
        error = payload.get("error") or {}
        return error.get("code") == "InputTextSensitiveContentDetected"

    def _sanitize_doubao_content_for_retry(
        self,
        *,
        content: List[Dict[str, Any]],
        segment: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        sanitized_content: List[Dict[str, Any]] = []
        for item in content:
            if (item or {}).get("type") != "text":
                sanitized_content.append(item)
                continue
            original_text = str((item or {}).get("text") or "")
            sanitized_text = self._sanitize_doubao_text(original_text)
            if not sanitized_text:
                sanitized_text = self._build_minimal_safe_doubao_text(segment)
            sanitized_content.append(
                {
                    "type": "text",
                    "text": sanitized_text,
                }
            )
        if not sanitized_content:
            sanitized_content.append({"type": "text", "text": self._build_minimal_safe_doubao_text(segment)})
        return sanitized_content

    def _sanitize_doubao_text(self, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return ""

        replacements = {
            "character profile ids": "character references",
            "scene profile": "scene setup",
            "Hard constraints": "Visual continuity constraints",
            "枪战": "对峙",
            "枪": "道具",
            "武器": "装备",
            "爆炸": "强烈冲击",
            "击杀": "制服",
            "杀死": "制服",
            "杀": "控制",
            "鲜血": "痕迹",
            "血": "痕迹",
            "尸体": "人物",
            "死亡": "倒地",
            "敌人": "对手",
            "军人": "角色",
            "特种兵": "角色",
            "战斗": "行动",
            "作战": "行动",
            "军事": "专业",
            "枪口": "镜头前景",
            "狙击": "远距观察",
            "gunfight": "confrontation",
            "gun": "prop",
            "weapon": "gear",
            "weapons": "gear",
            "kill": "stop",
            "killing": "stopping",
            "blood": "mark",
            "corpse": "person",
            "explosion": "impact",
            "enemy": "opponent",
            "battle": "encounter",
            "combat": "action",
            "military": "professional",
            "soldier": "character",
            "sniper": "observer",
        }
        for source, target in replacements.items():
            text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)

        text = re.sub(r"profile ids? [^.,;:\n]+", "character references", text, flags=re.IGNORECASE)
        text = re.sub(r"\b[a-f0-9]{8,}\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" ,.;:")
        return text[:1600]

    def _build_minimal_safe_doubao_text(self, segment: Dict[str, Any]) -> str:
        parts = [
            "Create a cinematic, coherent short video clip with stable character identity and environment continuity.",
            f"Scene summary: {self._sanitize_doubao_text(str(segment.get('description') or segment.get('title') or 'continuous scene'))}.",
        ]
        prompt_focus = self._sanitize_doubao_text(str(segment.get("prompt_focus") or ""))
        if prompt_focus:
            parts.append(f"Visual focus: {prompt_focus}.")
        continuity = self._sanitize_doubao_text(str(segment.get("continuity_to_next") or ""))
        if continuity:
            parts.append(f"Ending target: {continuity}.")
        parts.append("Natural motion, clean composition, no on-screen text, preserve face, outfit, silhouette, and color consistency.")
        return " ".join(parts)

    def _render_segment_gif(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        from PIL import Image, ImageDraw, ImageFont

        width, height = 960, 540
        clip_number = segment["segment_number"]
        font = ImageFont.load_default()
        frames = []

        start_image = self._load_local_image((keyframe_bundle or {}).get("start_frame", {}).get("asset_url"))
        end_image = self._load_local_image((keyframe_bundle or {}).get("end_frame", {}).get("asset_url"))

        if start_image and end_image:
            start_base = start_image.convert("RGB").resize((width, height))
            end_base = end_image.convert("RGB").resize((width, height))
            blend_steps = [0.0, 0.25, 0.5, 0.75, 1.0]

            for step in blend_steps:
                frame = Image.blend(start_base, end_base, step)
                draw = ImageDraw.Draw(frame)
                draw.rectangle((28, 24, width - 28, 86), fill=(0, 0, 0))
                draw.text((48, 44), f"Clip {clip_number:02d} | {segment['title'][:72]}", fill=(255, 200, 90), font=font)
                draw.text((48, height - 72), "Preview generated from approved keyframes", fill=(255, 255, 255), font=font)
                frames.append(frame)
        else:
            colors = [
                (27, 38, 59),
                (65, 90, 119),
                (120, 53, 15),
                (57, 102, 57),
                (107, 76, 154),
            ]
            base_color = colors[(clip_number - 1) % len(colors)]

            for frame_index in range(4):
                frame = Image.new(
                    "RGB",
                    (width, height),
                    (
                        min(base_color[0] + frame_index * 12, 255),
                        min(base_color[1] + frame_index * 10, 255),
                        min(base_color[2] + frame_index * 8, 255),
                    ),
                )
                draw = ImageDraw.Draw(frame)
                draw.rectangle((32, 28, width - 32, height - 28), outline=(255, 255, 255), width=3)
                draw.rectangle((52, 58, width - 52, 128), fill=(0, 0, 0))
                draw.text((72, 78), f"Clip {clip_number:02d}", fill=(255, 200, 90), font=font)
                draw.text((200, 78), segment["title"][:90], fill=(255, 255, 255), font=font)
                draw.text((72, 120), f"Duration: {segment['duration']:.1f}s", fill=(220, 220, 220), font=font)

                y = 170
                for line in self._wrap_lines(segment["description"] or segment["shots_summary"] or "暂无片段描述", width=52)[:8]:
                    draw.text((72, y), line, fill=(245, 245, 245), font=font)
                    y += 24

                y += 18
                draw.text((72, y), "Prompt", fill=(255, 200, 90), font=font)
                y += 28
                for line in self._wrap_lines(segment["video_prompt"] or "暂无视频提示词", width=52)[:6]:
                    draw.text((72, y), line, fill=(230, 230, 230), font=font)
                    y += 24
                frames.append(frame)

        filename = f"clip_{clip_number:02d}.gif"
        output_path = task_dir / filename
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=450,
            loop=0,
        )

        return {
            "asset_url": self._build_asset_url(output_path),
            "asset_type": "image/gif",
            "asset_filename": filename,
            "provider": "local-preview",
        }

    def _render_segment_svg(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        clip_number = segment["segment_number"]
        filename = f"clip_{clip_number:02d}.svg"
        output_path = task_dir / filename
        start_frame = (keyframe_bundle or {}).get("start_frame", {})
        end_frame = (keyframe_bundle or {}).get("end_frame", {})
        output_path.write_text(
            f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0b132b"/>
      <stop offset="100%" stop-color="#3a506b"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#bg)"/>
  <rect x="32" y="28" width="896" height="484" fill="none" stroke="#ffffff" stroke-width="3"/>
  <text x="72" y="86" fill="#ffc857" font-size="28" font-family="monospace">Clip {clip_number:02d}</text>
  <text x="72" y="124" fill="#ffffff" font-size="24" font-family="monospace">{escape(segment['title'][:96])}</text>
  <text x="72" y="162" fill="#d9d9d9" font-size="18" font-family="monospace">Duration: {segment['duration']:.1f}s</text>
  <text x="72" y="200" fill="#ffc857" font-size="18" font-family="monospace">Start: {escape(str(start_frame.get('asset_filename') or 'N/A'))}</text>
  <text x="72" y="232" fill="#ffc857" font-size="18" font-family="monospace">End: {escape(str(end_frame.get('asset_filename') or 'N/A'))}</text>
  <foreignObject x="72" y="268" width="816" height="120"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#f5f5f5;font-size:18px;line-height:1.5;font-family:monospace;white-space:pre-wrap;">{html.escape((segment['description'] or segment['shots_summary'] or '')[:420])}</div></foreignObject>
  <foreignObject x="72" y="402" width="816" height="90"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#d9d9d9;font-size:16px;line-height:1.5;font-family:monospace;white-space:pre-wrap;">{html.escape((segment['video_prompt'] or '')[:360])}</div></foreignObject>
</svg>
""",
            encoding="utf-8",
        )
        return {
            "asset_url": self._build_asset_url(output_path),
            "asset_type": "image/svg+xml",
            "asset_filename": filename,
            "provider": "local-preview",
        }

    async def _merge_video_clips(
        self,
        *,
        task_dir: Path,
        clips: List[RenderedClip],
        project_title: str,
        render_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        merger = VideoMergerService(output_dir=str(task_dir))

        segments = [
            MergedVideoSegment(
                id=str(index),
                video_url=clip.asset_url,
                duration=clip.duration,
                order=index,
            )
            for index, clip in enumerate(clips)
        ]
        output_filename = f"{self._slugify(project_title)}_final"
        result = await merger.merge_videos(
            segments=segments,
            options=MergeOptions(
                output_resolution=render_config.get("resolution", "720p"),
                output_format="mp4",
                add_watermark=render_config.get("watermark", False),
            ),
            output_filename=output_filename,
        )
        if result.get("status") != "success" or not result.get("output_path"):
            raise RuntimeError(result.get("error") or "Video merge failed")

        output_path = Path(result["output_path"])
        info = await merger.get_video_info(str(output_path))
        return {
            "asset_url": self._build_asset_url(output_path),
            "asset_type": "video/mp4",
            "asset_filename": output_path.name,
            "segment_count": len(clips),
            "provider": "doubao-official",
            "output_mode": "video",
            "video_info": info,
        }

    async def _merge_preview_assets(
        self,
        *,
        task_dir: Path,
        clips: List[RenderedClip],
        project_title: str,
        segments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if all(clip.asset_type == "image/gif" for clip in clips):
            try:
                return self._merge_gifs(task_dir=task_dir, clips=clips, project_title=project_title)
            except Exception as exc:
                logger.warning("GIF merge failed, fallback to SVG storyboard: %s", exc)
        return self._merge_svgs(task_dir=task_dir, project_title=project_title, segments=segments)

    def _merge_gifs(
        self,
        *,
        task_dir: Path,
        clips: List[RenderedClip],
        project_title: str,
    ) -> Dict[str, Any]:
        from PIL import Image, ImageSequence

        frames = []
        durations = []
        for clip in clips:
            clip_path = self._asset_url_to_path(clip.asset_url)
            if not clip_path or not clip_path.exists():
                continue
            with Image.open(clip_path) as image:
                for frame in ImageSequence.Iterator(image):
                    frames.append(frame.convert("P"))
                    durations.append(frame.info.get("duration", 450))

        if not frames:
            raise ValueError("No preview frames available for merge")

        filename = f"{self._slugify(project_title)}_final.gif"
        output_path = task_dir / filename
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=durations or 450,
            loop=0,
        )

        return {
            "asset_url": self._build_asset_url(output_path),
            "asset_type": "image/gif",
            "asset_filename": filename,
            "segment_count": len(clips),
            "provider": "local-preview",
            "output_mode": "preview",
        }

    def _merge_svgs(
        self,
        *,
        task_dir: Path,
        project_title: str,
        segments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        height = max(540 * len(segments), 540)
        parts = [
            f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{height}" viewBox="0 0 960 {height}">
  <rect width="960" height="{height}" fill="#101820"/>
  <text x="48" y="52" fill="#ffc857" font-size="28" font-family="monospace">Final Composite: {escape(project_title[:40])}</text>"""
        ]

        for index, segment in enumerate(segments):
            top = 90 + index * 540
            parts.extend(
                [
                    f'  <rect x="32" y="{top}" width="896" height="460" fill="#172033" stroke="#ffffff" stroke-width="2"/>',
                    f'  <text x="64" y="{top + 42}" fill="#ffc857" font-size="24" font-family="monospace">Clip {segment["segment_number"]:02d}</text>',
                    f'  <text x="220" y="{top + 42}" fill="#ffffff" font-size="22" font-family="monospace">{escape(segment["title"][:48])}</text>',
                    f'  <foreignObject x="64" y="{top + 76}" width="820" height="120"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#f5f5f5;font-size:18px;line-height:1.5;font-family:monospace;white-space:pre-wrap;">{html.escape((segment["description"] or segment["shots_summary"] or "")[:450])}</div></foreignObject>',
                    f'  <foreignObject x="64" y="{top + 220}" width="820" height="120"><div xmlns="http://www.w3.org/1999/xhtml" style="color:#d9d9d9;font-size:16px;line-height:1.5;font-family:monospace;white-space:pre-wrap;">{html.escape((segment["video_prompt"] or "")[:420])}</div></foreignObject>',
                ]
            )

        parts.append("</svg>")

        filename = f"{self._slugify(project_title)}_final.svg"
        output_path = task_dir / filename
        output_path.write_text("\n".join(parts), encoding="utf-8")

        return {
            "asset_url": self._build_asset_url(output_path),
            "asset_type": "image/svg+xml",
            "asset_filename": filename,
            "segment_count": len(segments),
            "provider": "local-preview",
            "output_mode": "preview",
        }

    def _can_merge_as_video(self, clips: Iterable[RenderedClip]) -> bool:
        return all(clip.asset_type.startswith("video/") for clip in clips)

    async def _finalize_project_audio(
        self,
        *,
        task_id: str,
        task_dir: Path,
        state: RenderTaskState,
        final_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        requested = bool(state.render_config.get("requested_generate_audio", True))
        if not requested:
            final_output["audio"] = {
                "status": "disabled",
                "strategy": state.render_config.get("audio_strategy", "mute"),
                "message": "用户关闭了统一音频生成，本次保留纯画面成片。",
            }
            return final_output

        if not bool(settings.AUDIO_PIPELINE_ENABLED):
            warning = "AUDIO_PIPELINE_ENABLED=false，已跳过项目级音频渲染。"
            if warning not in state.warnings:
                state.warnings.append(warning)
            final_output["audio"] = {
                "status": "skipped",
                "strategy": state.render_config.get("audio_strategy", "external_audio_pipeline"),
                "message": warning,
            }
            return final_output

        if not str(final_output.get("asset_type") or "").startswith("video/"):
            warning = "最终输出不是视频文件，当前音频链路只支持对真实视频进行混音与 mux。"
            if warning not in state.warnings:
                state.warnings.append(warning)
            final_output["audio"] = {
                "status": "skipped",
                "strategy": state.render_config.get("audio_strategy", "external_audio_pipeline"),
                "message": warning,
            }
            return final_output

        video_path = self._asset_url_to_path(str(final_output.get("asset_url") or "").strip())
        if video_path is None or not video_path.exists():
            warning = "最终视频文件不存在，无法执行项目级音频渲染。"
            if warning not in state.warnings:
                state.warnings.append(warning)
            final_output["audio"] = {
                "status": "skipped",
                "strategy": state.render_config.get("audio_strategy", "external_audio_pipeline"),
                "message": warning,
            }
            return final_output

        state.current_step = "生成项目级音频"
        state.progress = 92.0
        state.touch()
        await self._persist_render_task_state(state=state)

        try:
            audio_renderer = ProjectAudioRenderer(
                output_dir=str(task_dir),
                sample_rate=int(settings.AUDIO_SAMPLE_RATE),
                channels=int(settings.AUDIO_CHANNELS),
                master_codec=str(settings.AUDIO_MASTER_CODEC or "aac"),
                master_bitrate=str(settings.AUDIO_MASTER_BITRATE or "192k"),
                tts_provider=str(settings.AUDIO_TTS_PROVIDER or "mock-silent"),
                sfx_provider=str(settings.AUDIO_SFX_PROVIDER or "mock-silent"),
                ambience_provider=str(settings.AUDIO_AMBIENCE_PROVIDER or "mock-silent"),
                music_provider=str(settings.AUDIO_MUSIC_PROVIDER or "mock-silent"),
            )
            audio_result = await audio_renderer.render_project_audio(
                video_path=str(video_path),
                audio_plan=dict(state.render_config.get("audio_plan") or {}),
                project_title=state.project_title,
                output_basename=f"{self._slugify(state.project_title)}_{task_id[:8]}",
                expected_duration=self._extract_media_duration(final_output),
            )
        except Exception as exc:
            warning = f"项目级音频渲染失败，已保留无音频成片: {exc}"
            logger.warning("Project audio rendering failed for task %s: %s", task_id, exc, exc_info=True)
            if warning not in state.warnings:
                state.warnings.append(warning)
            final_output["audio"] = {
                "status": "failed",
                "strategy": state.render_config.get("audio_strategy", "external_audio_pipeline"),
                "message": warning,
            }
            return final_output

        for warning in audio_result.get("warnings") or []:
            if warning not in state.warnings:
                state.warnings.append(str(warning))

        final_output["audio"] = {
            "status": audio_result.get("status", "completed"),
            "strategy": audio_result.get("strategy", state.render_config.get("audio_strategy", "external_audio_pipeline")),
            "providers": audio_result.get("providers") or {},
            "duration": audio_result.get("duration"),
            "manifest_url": self._build_optional_asset_url(audio_result.get("manifest_path")),
            "master_audio_url": self._build_optional_asset_url(audio_result.get("master_audio_path")),
            "muxed_video_url": self._build_optional_asset_url(audio_result.get("muxed_video_path")),
            "warnings": audio_result.get("warnings") or [],
        }

        muxed_video_path_raw = str(audio_result.get("muxed_video_path") or "").strip()
        muxed_video_path = Path(muxed_video_path_raw).expanduser() if muxed_video_path_raw else None
        if muxed_video_path is None or not muxed_video_path.exists():
            warning = "项目级音频流程未产出 mux 后视频，已保留无音频成片。"
            if warning not in state.warnings:
                state.warnings.append(warning)
            return final_output

        final_output["video_without_audio"] = {
            "asset_url": final_output.get("asset_url"),
            "asset_type": final_output.get("asset_type"),
            "asset_filename": final_output.get("asset_filename"),
        }
        final_output["asset_url"] = self._build_asset_url(muxed_video_path)
        final_output["asset_type"] = "video/mp4"
        final_output["asset_filename"] = muxed_video_path.name

        merger = VideoMergerService(output_dir=str(task_dir))
        final_output["video_info"] = await merger.get_video_info(str(muxed_video_path))
        return final_output

    def _doubao_enabled(self) -> bool:
        return bool(self._get_doubao_api_key())

    def _get_doubao_api_key(self) -> Optional[str]:
        return get_effective_doubao_api_key()

    def _kling_enabled(self) -> bool:
        return kling_credentials_configured()

    def _get_kling_credentials(self) -> tuple[Optional[str], Optional[str]]:
        return get_effective_kling_credentials()

    def _build_project_audio_plan(
        self,
        *,
        segments: List[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        provider_generate_audio = bool(render_config.get("generate_audio", True))
        requested_generate_audio = bool(render_config.get("requested_generate_audio", True))
        if not requested_generate_audio:
            if provider_generate_audio:
                return {
                    "strategy": "provider_native",
                    "provider_audio_disabled": False,
                    "requested_generate_audio": False,
                    "summary": "当前不执行项目级音频后处理，交由视频模型自身生成音频特效。",
                    "mix_principles": [],
                    "character_voice_bible": [],
                    "music_bible": {
                        "global_direction": "",
                        "avoid": [],
                    },
                    "ambience_bible": [],
                    "segment_audio_plan": [],
                }
            return {
                "strategy": "mute",
                "provider_audio_disabled": True,
                "requested_generate_audio": False,
                "summary": "本次任务只生成纯画面视频，不规划外部音频。",
                "mix_principles": [],
                "character_voice_bible": [],
                "music_bible": {
                    "global_direction": "",
                    "avoid": [],
                },
                "ambience_bible": [],
                "segment_audio_plan": [],
            }

        active_character_ids: List[str] = []
        for segment in segments:
            for profile_id in segment.get("character_profile_ids") or []:
                normalized_id = str(profile_id).strip()
                if normalized_id and normalized_id not in active_character_ids:
                    active_character_ids.append(normalized_id)

        active_characters = [
            profile for profile in character_profiles
            if not active_character_ids or str(profile.get("id") or "").strip() in active_character_ids
        ]
        if not active_characters:
            active_characters = list(character_profiles or [])

        active_scene_ids = {
            str(segment.get("scene_profile_id") or "").strip()
            for segment in segments
            if str(segment.get("scene_profile_id") or "").strip()
        }
        active_scenes = [
            profile for profile in scene_profiles
            if not active_scene_ids or str(profile.get("id") or "").strip() in active_scene_ids
        ]
        if not active_scenes:
            active_scenes = list(scene_profiles or [])

        character_voice_bible = []
        for profile in active_characters:
            speaking_style = str(profile.get("speaking_style") or "").strip()
            personality = str(profile.get("personality") or "").strip()
            role = str(profile.get("role") or "").strip()
            must_keep = self._ensure_text_list(profile.get("must_keep") or [])
            voice_description = self._normalize_voice_description(profile.get("voice_description") or "")
            character_voice_bible.append(
                {
                    "character_id": str(profile.get("id") or "").strip(),
                    "name": str(profile.get("name") or "").strip(),
                    "role": role,
                    "speaking_style": speaking_style,
                    "emotion_baseline": str(profile.get("emotion_baseline") or "").strip(),
                    "voice_description": voice_description,
                    "voice_direction": self._join_audio_parts(
                        [
                            role,
                            speaking_style,
                            personality,
                            f"角色识别点：{'、'.join(must_keep[:3])}" if must_keep else "",
                            f"音色设定：{voice_description}" if voice_description else "",
                        ]
                    ),
                }
            )

        ambience_bible = []
        for profile in active_scenes:
            must_have = self._ensure_text_list(profile.get("must_have_elements") or [])
            ambience_bible.append(
                {
                    "scene_profile_id": str(profile.get("id") or "").strip(),
                    "name": str(profile.get("name") or "").strip(),
                    "atmosphere": str(profile.get("atmosphere") or "").strip(),
                    "lighting": str(profile.get("lighting") or "").strip(),
                    "ambience_direction": self._join_audio_parts(
                        [
                            str(profile.get("scene_type") or "").strip(),
                            str(profile.get("location") or "").strip(),
                            str(profile.get("atmosphere") or "").strip(),
                            f"环境锚点：{'、'.join(must_have[:3])}" if must_have else "",
                        ]
                    ),
                }
            )

        segment_audio_plan = [
            self._build_segment_audio_plan(
                segment=segment,
                character_profiles=character_profiles,
                scene_profiles=scene_profiles,
            )
            for segment in segments
        ]
        all_music_tags = self._unique_preserve_order(
            plan.get("music_direction", "")
            for plan in segment_audio_plan
            if str(plan.get("music_direction") or "").strip()
        )

        return {
            "strategy": "external_audio_pipeline",
            "provider_audio_disabled": True,
            "requested_generate_audio": True,
            "summary": "视频模型只负责画面生成，音频统一由外部音频链路按项目级规划生成并最终混音。",
            "mix_principles": [
                "整片使用统一角色声线，不跟随单段视频模型漂移。",
                "对白优先，音乐和环境音为连续层，不在片段切换处突变。",
                "新角色首次登场时提高人声清晰度，帮助观众建立稳定识别。",
                "片尾保留角色或环境尾音，为下一段首帧续接提供听觉锚点。",
            ],
            "character_voice_bible": character_voice_bible,
            "music_bible": {
                "global_direction": "延续同一套配乐母题和质感，避免每段重新起风格。",
                "suggested_motifs": all_music_tags[:6],
                "avoid": [
                    "每段完全不同的人声音色",
                    "片段间音乐调性突然跳变",
                    "环境底噪忽有忽无",
                ],
            },
            "ambience_bible": ambience_bible,
            "segment_audio_plan": segment_audio_plan,
        }

    def _build_segment_audio_plan(
        self,
        *,
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        segment_characters, segment_scene = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        character_names = self._unique_preserve_order(
            str(profile.get("name") or "").strip()
            for profile in segment_characters
            if str(profile.get("name") or "").strip()
        )
        dialogue_lines = self._resolve_segment_dialogue_bindings(
            self._normalize_segment_dialogues(segment.get("key_dialogues") or []),
            segment_characters=segment_characters,
        )[:4]
        dialogue_focus = [
            str(item.get("text") or "").strip()
            for item in dialogue_lines
            if str(item.get("text") or "").strip()
        ]
        action_focus = self._ensure_text_list(segment.get("key_actions") or [])[:5]
        voice_tracks = []
        for profile in segment_characters:
            voice_tracks.append(
                {
                    "character_id": str(profile.get("id") or "").strip(),
                    "name": str(profile.get("name") or "").strip(),
                    "speaking_style": str(profile.get("speaking_style") or "").strip(),
                    "emotion_baseline": str(profile.get("emotion_baseline") or "").strip(),
                    "voice_description": self._normalize_voice_description(
                        profile.get("voice_description") or ""
                    ),
                }
            )

        scene_name = str(segment_scene.get("name") or "").strip() if segment_scene else ""
        scene_atmosphere = str(segment_scene.get("atmosphere") or "").strip() if segment_scene else ""
        scene_location = str(segment_scene.get("location") or "").strip() if segment_scene else ""
        scene_props = self._ensure_text_list((segment_scene or {}).get("props_must_have") or [])[:4]
        scene_camera = self._ensure_text_list((segment_scene or {}).get("camera_preferences") or [])[:2]

        sound_effects = self._unique_preserve_order(
            [*action_focus, *(scene_props or []), *(scene_camera or [])]
        )[:6]

        music_direction_parts = [
            scene_atmosphere,
            str(segment.get("prompt_focus") or "").strip(),
            str(segment.get("transition_out") or "").strip(),
        ]
        if segment.get("contains_primary_character"):
            music_direction_parts.append("主角存在感要稳定，不要被音效盖住")
        if segment.get("new_character_profile_ids"):
            music_direction_parts.append("新角色登场时配乐先让位给声线辨识")
        music_direction = self._join_audio_parts(music_direction_parts)

        mix_notes = []
        if dialogue_focus:
            mix_notes.append("对白置于前景，优先保证台词清晰度。")
        if segment.get("ending_contains_primary_character") or segment.get("ending_contains_handoff_characters"):
            mix_notes.append("片尾保留角色呼吸、脚步或衣料尾音，帮助下一段衔接。")
        if segment.get("prefer_primary_character_end_frame") or segment.get("prefer_character_handoff_end_frame"):
            mix_notes.append("结尾避免音乐硬切，使用环境尾音或短延音过渡。")
        if segment.get("continuity_to_next"):
            mix_notes.append(f"与下一段衔接提示：{str(segment.get('continuity_to_next') or '').strip()}")

        return {
            "segment_number": int(segment.get("segment_number") or 0),
            "title": str(segment.get("title") or ""),
            "duration": float(segment.get("duration") or 0.0),
            "characters": character_names,
            "voice_tracks": voice_tracks,
            "dialogue_focus": dialogue_focus,
            "dialogue_lines": dialogue_lines,
            "sound_effects": sound_effects,
            "ambience": self._join_audio_parts([scene_name, scene_location, scene_atmosphere]),
            "music_direction": music_direction,
            "transition_hint": str(segment.get("continuity_to_next") or segment.get("continuity_from_prev") or "").strip(),
            "mix_notes": mix_notes,
        }

    def _ensure_text_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, tuple):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        return []

    def _unique_preserve_order(self, values: Iterable[Any]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _join_audio_parts(self, parts: Iterable[Any]) -> str:
        normalized = self._unique_preserve_order(parts)
        return "；".join(normalized[:4])

    def _normalize_voice_description(self, value: Any) -> str:
        return str(value or "").strip()

    def _normalize_render_config(self, render_config: Dict[str, Any]) -> Dict[str, Any]:
        provider_generate_audio = bool(render_config.get("generate_audio", True))
        return {
            "provider": str(render_config.get("provider") or "auto"),
            "resolution": self._normalize_doubao_resolution(str(render_config.get("resolution") or "720p")),
            "aspect_ratio": self._normalize_doubao_aspect_ratio(str(render_config.get("aspect_ratio") or "16:9")),
            "watermark": bool(render_config.get("watermark", False)),
            "provider_model": str(render_config.get("provider_model") or ""),
            "camera_fixed": bool(render_config.get("camera_fixed", False)),
            "generate_audio": provider_generate_audio,
            "requested_generate_audio": False,
            "audio_strategy": "provider_native" if provider_generate_audio else "mute",
            "audio_plan": None,
            "return_last_frame": True,
            "auto_continue_segments": bool(render_config.get("auto_continue_segments", False)),
            "service_tier": self._normalize_service_tier(str(render_config.get("service_tier") or "default")),
            "seed": self._normalize_provider_seed(render_config.get("seed")),
        }

    def _build_doubao_content(
        self,
        *,
        task_dir: Optional[Path],
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        segment_characters, _ = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        prompt = self._build_segment_video_prompt(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        negative_prompt = self._build_segment_negative_prompt(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        if negative_prompt:
            prompt = f"{prompt}\nAvoid: {negative_prompt}"

        start_frame = ""
        character_anchor_images: List[Dict[str, Any]] = []
        if keyframe_bundle:
            start_frame = (keyframe_bundle.get("start_frame") or {}).get("asset_url") or ""
            character_anchor_images = self._build_video_character_reference_images(
                task_dir=task_dir,
                segment=segment,
                character_profiles=segment_characters,
            )

        if start_frame:
            anchor_labels = [str(item.get("label") or item.get("anchor_type") or "").strip() for item in character_anchor_images]
            if character_anchor_images:
                logger.info(
                    "Using start frame as the only image input for segment %s; %s character anchor images stay in text guidance only: %s",
                    segment.get("segment_number"),
                    len(character_anchor_images),
                    ", ".join(label for label in anchor_labels if label) or "unnamed anchors",
                )
            else:
                logger.info(
                    "Using start frame as the only image input for segment %s; next clip start will come from provider returned last frame",
                    segment.get("segment_number"),
                )
            final_moment_hint = (
                segment.get("continuity_to_next")
                or segment.get("description")
                or segment.get("shots_summary")
                or segment.get("title")
            )
            prompt = (
                f"{prompt}\n"
                "Treat the provided first-frame image as the highest-priority motion and continuity anchor; do not reinvent shot composition from narrative text. "
                "Use the character identity and continuity instructions in the text as the identity lock for face, hairstyle, outfit, silhouette, and color palette. "
                "Keep the motion consistent with the first-frame image while preserving the subject identity described in the text guidance. "
                f"The final moment should land on this target ending state: {final_moment_hint}."
            )
        elif character_anchor_images:
            prompt = (
                f"{prompt}\n"
                "No image anchor is attached for this clip. "
                "Rely on the character identity and continuity instructions in the text to keep face, hairstyle, outfit, silhouette, and color palette stable during motion."
            )

        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        if not keyframe_bundle:
            return content

        image_candidates: List[Dict[str, str]] = []
        if start_frame:
            image_candidates.append(
                {
                    "url": start_frame,
                    "label": "start_frame",
                }
            )

        provider_images: List[Dict[str, str]] = []
        for candidate in image_candidates:
            provider_image_url = self._build_provider_image_reference(candidate["url"])
            if provider_image_url:
                provider_images.append(
                    {
                        "url": provider_image_url,
                        "label": candidate["label"],
                    }
                )

        if provider_images:
            content.append({"type": "image_url", "image_url": {"url": provider_images[0]["url"]}})

        return content

    def _get_segment_profile_context(
        self,
        *,
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        character_ids = {str(item).strip() for item in (segment.get("character_profile_ids") or []) if str(item).strip()}
        scene_profile_id = str(segment.get("scene_profile_id") or "").strip()
        filtered_characters = [
            profile for profile in character_profiles
            if not character_ids or str(profile.get("id") or "").strip() in character_ids
        ]
        filtered_scene = next(
            (profile for profile in scene_profiles if str(profile.get("id") or "").strip() == scene_profile_id),
            scene_profiles[0] if scene_profiles else None,
        )
        return filtered_characters or character_profiles, filtered_scene

    def _build_keyframe_reference_images(
        self,
        *,
        task_dir: Path,
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        reference_images: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        segment_characters, segment_scene = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        merged: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()

        character_reference_images = self._build_balanced_character_reference_images(
            task_dir=task_dir,
            segment=segment,
            character_profiles=segment_characters,
            max_images=MAX_KEYFRAME_CHARACTER_ANCHOR_IMAGES,
            stage="keyframe",
        )
        for item in character_reference_images:
            self._append_reference_image(merged, seen_urls, item)

        scene_reference = str((segment_scene or {}).get("reference_image_url") or "").strip()
        if scene_reference and scene_reference not in seen_urls:
            merged.append(
                {
                    "id": f"{segment_scene.get('id') or 'scene'}-reference",
                    "url": scene_reference,
                    "filename": scene_reference.split("/")[-1] or "scene_reference.png",
                    "original_filename": scene_reference.split("/")[-1] or "scene_reference.png",
                    "content_type": "image/png",
                    "size": 0,
                    "source": "scene-reference",
                    "anchor_type": "scene_reference",
                    "label": f"{segment_scene.get('name') or '场景'}参考图",
                }
            )
            seen_urls.add(scene_reference)

        for item in reference_images:
            url = str(item.get("url") or "").strip()
            if url and url not in seen_urls:
                merged.append(item)
                seen_urls.add(url)

        return merged

    def _build_character_identity_reference_images(self, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        def build_item(anchor_type: str, label: str, url: str) -> Optional[Dict[str, Any]]:
            normalized_url = str(url or "").strip()
            if not normalized_url:
                return None
            filename = normalized_url.split("/")[-1] or f"{anchor_type}.png"
            return {
                "id": f"{profile.get('id') or profile.get('name') or 'character'}-{anchor_type}",
                "url": normalized_url,
                "filename": filename,
                "original_filename": filename,
                "content_type": "image/png",
                "size": 0,
                "source": "character-identity-anchor",
                "anchor_type": anchor_type,
                "label": f"{profile.get('name') or '角色'}{label}",
            }

        items = [
            build_item("main_reference", "主参考图", profile.get("reference_image_url") or ""),
            build_item("three_view", "三视图", profile.get("three_view_image_url") or ""),
            build_item("face_closeup", "面部特写", profile.get("face_closeup_image_url") or ""),
        ]
        return [item for item in items if item]

    def _append_reference_image(
        self,
        merged: List[Dict[str, Any]],
        seen_urls: set[str],
        item: Optional[Dict[str, Any]],
        max_images: Optional[int] = None,
    ) -> bool:
        if not item:
            return False
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            return False
        if max_images is not None and len(merged) >= max_images:
            return False
        merged.append(item)
        seen_urls.add(url)
        return True

    def _build_character_anchor_candidates(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        anchor_lookup: Dict[str, Dict[str, Any]] = {}
        for item in self._build_character_identity_reference_images(profile):
            anchor_type = str(item.get("anchor_type") or "").strip()
            if anchor_type and anchor_type not in anchor_lookup:
                anchor_lookup[anchor_type] = item

        primary = (
            anchor_lookup.get("main_reference")
            or anchor_lookup.get("face_closeup")
            or anchor_lookup.get("three_view")
        )
        supplements: List[Dict[str, Any]] = []
        primary_url = str((primary or {}).get("url") or "").strip()
        for anchor_type in ["face_closeup", "three_view", "main_reference"]:
            item = anchor_lookup.get(anchor_type)
            url = str((item or {}).get("url") or "").strip()
            if item and url and url != primary_url:
                supplements.append(item)

        return {
            "profile": profile,
            "primary": primary,
            "supplements": supplements,
            "lookup": anchor_lookup,
        }

    def _build_multi_character_identity_board(
        self,
        *,
        task_dir: Optional[Path],
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        stage: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageOps
        except ModuleNotFoundError:
            logger.warning(
                "PIL is unavailable, skip multi-character identity board for segment %s stage=%s",
                segment.get("segment_number"),
                stage,
            )
            return None

        cards: List[Dict[str, Any]] = []
        for profile in character_profiles:
            anchor_lookup = self._build_character_anchor_candidates(profile).get("lookup") or {}
            image_paths: Dict[str, Path] = {}
            for anchor_type in ["main_reference", "face_closeup", "three_view"]:
                item = anchor_lookup.get(anchor_type)
                path = self._asset_url_to_path(str((item or {}).get("url") or "").strip())
                if path and path.exists():
                    image_paths[anchor_type] = path
            if image_paths:
                cards.append({"profile": profile, "image_paths": image_paths})

        if len(cards) < 2:
            return None

        board_dir = (task_dir / "identity_boards") if task_dir else self.identity_board_root
        board_dir.mkdir(parents=True, exist_ok=True)

        board_width = 2048
        padding = 48
        header_height = 120
        gap = 28
        columns = 2 if len(cards) > 1 else 1
        rows = max(1, (len(cards) + columns - 1) // columns)
        card_width = int((board_width - padding * 2 - gap * (columns - 1)) / columns)
        card_height = max(420, int((2048 - padding * 2 - header_height - gap * max(rows - 1, 0)) / rows))
        board_height = padding + header_height + rows * card_height + gap * max(rows - 1, 0) + padding

        board = Image.new("RGB", (board_width, board_height), "#0f1726")
        draw = ImageDraw.Draw(board)
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()

        title = f"Segment {int(segment.get('segment_number') or 0):02d} Character Identity Board"
        subtitle = "All on-screen characters must stay consistent with these anchors."
        draw.text((padding, padding), title, fill="#f8d37a", font=font_title)
        draw.text((padding, padding + 34), subtitle, fill="#d7e3ff", font=font_text)

        for index, card in enumerate(cards):
            col = index % columns
            row = index // columns
            left = padding + col * (card_width + gap)
            top = padding + header_height + row * (card_height + gap)
            right = left + card_width
            bottom = top + card_height

            draw.rounded_rectangle((left, top, right, bottom), radius=24, fill="#18263d", outline="#36507b", width=3)

            inner_left = left + 20
            inner_top = top + 20
            inner_right = right - 20
            inner_bottom = bottom - 20
            inner_width = inner_right - inner_left
            inner_height = inner_bottom - inner_top

            main_box = (
                inner_left,
                inner_top + 52,
                inner_left + int(inner_width * 0.62),
                inner_bottom,
            )
            detail_left = main_box[2] + 16
            detail_box_top = inner_top + 52
            detail_box_width = inner_right - detail_left
            detail_box_height = int((inner_bottom - detail_box_top - 14) / 2)
            face_box = (
                detail_left,
                detail_box_top,
                inner_right,
                detail_box_top + detail_box_height,
            )
            view_box = (
                detail_left,
                detail_box_top + detail_box_height + 14,
                inner_right,
                inner_bottom,
            )

            profile = card["profile"]
            must_keep = ", ".join((profile.get("must_keep") or [])[:3])
            title_text = str(profile.get("name") or "角色")
            meta_text = must_keep or str(profile.get("core_appearance") or "").strip()[:44]
            draw.text((inner_left, inner_top), title_text[:28], fill="#ffffff", font=font_title)
            if meta_text:
                draw.text((inner_left, inner_top + 22), meta_text[:56], fill="#b9c7de", font=font_text)

            def paste_box(box: tuple[int, int, int, int], path: Optional[Path], fallback_label: str) -> None:
                draw.rounded_rectangle(box, radius=16, fill="#101827", outline="#2f466b", width=2)
                if not path:
                    draw.text((box[0] + 12, box[1] + 12), fallback_label, fill="#91a4c7", font=font_text)
                    return
                with Image.open(path) as opened:
                    prepared = ImageOps.fit(opened.convert("RGB"), (box[2] - box[0], box[3] - box[1]))
                board.paste(prepared, (box[0], box[1]))

            image_paths = card["image_paths"]
            paste_box(
                main_box,
                image_paths.get("main_reference") or image_paths.get("face_closeup") or image_paths.get("three_view"),
                "Main anchor",
            )
            paste_box(face_box, image_paths.get("face_closeup"), "Face closeup")
            paste_box(view_box, image_paths.get("three_view"), "Three-view")

        asset_id = uuid.uuid4().hex[:12]
        safe_name = f"segment_{int(segment.get('segment_number') or 0):02d}_{stage}_{asset_id}_identity_board.png"
        output_path = board_dir / safe_name
        board.save(output_path, format="PNG")

        return {
            "id": f"segment-{segment.get('segment_number') or 'x'}-identity-board",
            "url": self._build_asset_url(output_path),
            "filename": safe_name,
            "original_filename": safe_name,
            "content_type": "image/png",
            "size": output_path.stat().st_size,
            "source": "character-identity-board",
            "anchor_type": "character_identity_board",
            "label": f"片段{segment.get('segment_number') or ''}多角色身份板",
        }

    def _build_balanced_character_reference_images(
        self,
        *,
        task_dir: Optional[Path],
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        max_images: int,
        stage: str,
    ) -> List[Dict[str, Any]]:
        selected_items: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        candidates = [self._build_character_anchor_candidates(profile) for profile in character_profiles]
        candidates = [item for item in candidates if item.get("primary") or item.get("supplements")]

        if stage != "video" and len(candidates) > 1:
            board_item = self._build_multi_character_identity_board(
                task_dir=task_dir,
                segment=segment,
                character_profiles=[item["profile"] for item in candidates],
                stage=stage,
            )
            self._append_reference_image(selected_items, seen_urls, board_item, max_images)

        for candidate in candidates:
            self._append_reference_image(selected_items, seen_urls, candidate.get("primary"), max_images)

        while len(selected_items) < max_images:
            progressed = False
            for candidate in candidates:
                supplements = candidate.get("supplements") or []
                if not supplements:
                    continue
                next_item = supplements.pop(0)
                if self._append_reference_image(selected_items, seen_urls, next_item, max_images):
                    progressed = True
                if len(selected_items) >= max_images:
                    break
            if not progressed:
                break

        return selected_items

    def _build_video_character_reference_images(
        self,
        *,
        task_dir: Optional[Path],
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        max_images: int = MAX_VIDEO_CHARACTER_ANCHOR_IMAGES,
    ) -> List[Dict[str, Any]]:
        return self._build_balanced_character_reference_images(
            task_dir=task_dir,
            segment=segment,
            character_profiles=character_profiles,
            max_images=max_images,
            stage="video",
        )

    def _build_character_identity_anchor_pack(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "character_id": str(profile.get("id") or "").strip(),
            "profile_version": int(profile.get("profile_version") or 1),
            "display_image_url": str(profile.get("reference_image_url") or "").strip(),
            "three_view_image_url": str(profile.get("three_view_image_url") or "").strip(),
            "face_closeup_image_url": str(profile.get("face_closeup_image_url") or "").strip(),
            "must_keep": list(profile.get("must_keep") or []),
            "forbidden_traits": list(profile.get("forbidden_traits") or []),
            "core_appearance": str(profile.get("core_appearance") or "").strip(),
            "outfit": str(profile.get("outfit") or "").strip(),
            "color_palette": str(profile.get("color_palette") or "").strip(),
            "speaking_style": str(profile.get("speaking_style") or "").strip(),
            "voice_description": self._normalize_voice_description(profile.get("voice_description") or ""),
            "common_actions": str(profile.get("common_actions") or "").strip(),
            "llm_summary": str(profile.get("llm_summary") or "").strip(),
            "image_prompt_base": str(profile.get("image_prompt_base") or "").strip(),
            "video_prompt_base": str(profile.get("video_prompt_base") or "").strip(),
        }

    def _describe_reference_images(self, reference_images: List[Dict[str, Any]]) -> str:
        labels = [
            str(item.get("label") or item.get("anchor_type") or item.get("filename") or "").strip()
            for item in reference_images
            if str(item.get("url") or "").strip()
        ]
        unique_labels: List[str] = []
        for label in labels:
            if label and label not in unique_labels:
                unique_labels.append(label)
        return ", ".join(unique_labels[:8]) or f"{len(reference_images)} reference images"

    def _build_segment_image_prompt_base(
        self,
        character_profiles: List[Dict[str, Any]],
        scene_profile: Optional[Dict[str, Any]],
    ) -> str:
        parts: List[str] = []
        for profile in character_profiles:
            base = str(profile.get("image_prompt_base") or "").strip()
            if base:
                parts.append(f"{profile.get('name')}: {base}")
        if scene_profile:
            scene_base = str(scene_profile.get("image_prompt_base") or "").strip()
            if scene_base:
                parts.append(f"{scene_profile.get('name')}: {scene_base}")
        return " | ".join(parts)

    def _build_segment_video_prompt_base(
        self,
        character_profiles: List[Dict[str, Any]],
        scene_profile: Optional[Dict[str, Any]],
    ) -> str:
        parts: List[str] = []
        for profile in character_profiles:
            base = str(profile.get("video_prompt_base") or "").strip()
            if base:
                parts.append(f"{profile.get('name')}: {base}")
        if scene_profile:
            scene_base = str(scene_profile.get("video_prompt_base") or "").strip()
            if scene_base:
                parts.append(f"{scene_profile.get('name')}: {scene_base}")
        return " | ".join(parts)

    def _build_character_image_base(self, profile: Dict[str, Any]) -> str:
        return "；".join(
            part
            for part in [
                str(profile.get("name") or "").strip(),
                str(profile.get("image_prompt_base") or "").strip(),
                str(profile.get("core_appearance") or "").strip(),
                str(profile.get("face_features") or "").strip(),
                str(profile.get("outfit") or "").strip(),
                str(profile.get("gear") or "").strip(),
                str(profile.get("color_palette") or "").strip(),
                f"must keep: {', '.join(profile.get('must_keep') or [])}" if profile.get("must_keep") else "",
            ]
            if part
        )

    def _build_scene_image_base(self, profile: Dict[str, Any]) -> str:
        return "；".join(
            part
            for part in [
                str(profile.get("name") or "").strip(),
                str(profile.get("image_prompt_base") or "").strip(),
                str(profile.get("location") or "").strip(),
                str(profile.get("lighting") or "").strip(),
                str(profile.get("atmosphere") or "").strip(),
            ]
            if part
        )

    def _build_character_video_base(self, profile: Dict[str, Any]) -> str:
        voice_anchor = self._build_character_voice_anchor(profile)
        return "；".join(
            part
            for part in [
                str(profile.get("name") or "").strip(),
                str(profile.get("video_prompt_base") or "").strip(),
                str(profile.get("core_appearance") or "").strip(),
                str(profile.get("speaking_style") or "").strip(),
                voice_anchor,
                str(profile.get("common_actions") or "").strip(),
                f"must keep: {', '.join(profile.get('must_keep') or [])}" if profile.get("must_keep") else "",
            ]
            if part
        )

    def _build_character_voice_anchor(self, profile: Dict[str, Any]) -> str:
        parts: List[str] = []

        speaking_style = str(profile.get("speaking_style") or "").strip()
        if speaking_style:
            parts.append(f"说话方式:{speaking_style}")

        emotion_baseline = str(profile.get("emotion_baseline") or "").strip()
        if emotion_baseline:
            parts.append(f"常态情绪:{emotion_baseline}")

        voice_description = self._normalize_voice_description(profile.get("voice_description") or "")
        if voice_description:
            parts.append(f"音色设定:{voice_description}")

        if not parts:
            return ""

        return "voice anchor: " + "；".join(parts)

    def _build_segment_voice_continuity_instruction(
        self,
        character_profiles: List[Dict[str, Any]],
    ) -> str:
        anchors: List[str] = []
        for profile in character_profiles:
            name = str(profile.get("name") or "").strip()
            voice_anchor = self._build_character_voice_anchor(profile)
            if name and voice_anchor:
                anchors.append(f"{name}: {voice_anchor}")
            elif voice_anchor:
                anchors.append(voice_anchor)

        if not anchors:
            return ""

        return (
            "Voice continuity anchors: "
            + " | ".join(anchors)
            + ". If this clip contains spoken lines, breathing, laughter, cries, shouts, or any vocal reaction, "
              "keep each character's timbre, delivery style, and emotional baseline stable across the whole clip, "
              "and do not let different characters drift into the same voice."
        )

    def _build_scene_video_base(self, profile: Dict[str, Any]) -> str:
        return "；".join(
            part
            for part in [
                str(profile.get("name") or "").strip(),
                str(profile.get("video_prompt_base") or "").strip(),
                str(profile.get("scene_rules") or "").strip(),
                str(profile.get("camera_preferences") and ', '.join(profile.get("camera_preferences") or []) or "").strip(),
            ]
            if part
        )

    def _build_segment_hard_constraints(
        self,
        character_profiles: List[Dict[str, Any]],
        scene_profile: Optional[Dict[str, Any]],
    ) -> str:
        constraints: List[str] = []
        for profile in character_profiles:
            must_keep = profile.get("must_keep") or []
            if must_keep:
                constraints.append(f"Keep {profile.get('name')}: {', '.join(must_keep)}")
            forbidden_traits = profile.get("forbidden_traits") or []
            if forbidden_traits:
                constraints.append(f"Do not change {profile.get('name')} into: {', '.join(forbidden_traits)}")
        if scene_profile:
            must_have = scene_profile.get("must_have_elements") or scene_profile.get("props_must_have") or []
            if must_have:
                constraints.append(f"Scene must include: {', '.join(must_have)}")
            forbidden_elements = scene_profile.get("forbidden_elements") or scene_profile.get("props_forbidden") or []
            if forbidden_elements:
                constraints.append(f"Scene must avoid: {', '.join(forbidden_elements)}")
        if not constraints:
            return ""
        return "Hard constraints: " + " | ".join(constraints) + ". "

    def _build_segment_video_prompt(
        self,
        *,
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
    ) -> str:
        segment_characters, segment_scene = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        parts: List[str] = []
        if segment_characters:
            parts.append("Character continuity anchors: " + " | ".join(self._build_character_video_base(item) for item in segment_characters))
        if segment_scene:
            parts.append("Scene continuity: " + self._build_scene_video_base(segment_scene))
        stable_video_base = self._build_segment_video_prompt_base(segment_characters, segment_scene)
        if stable_video_base:
            parts.append(f"Stable video base: {stable_video_base}")
        voice_continuity = self._build_segment_voice_continuity_instruction(segment_characters)
        if voice_continuity:
            parts.append(voice_continuity)
        if segment.get("prompt_focus"):
            parts.append(f"Current clip focus: {segment['prompt_focus']}")
        if segment.get("shots_summary"):
            parts.append(f"Shot chain: {segment['shots_summary']}")
        if segment.get("video_prompt"):
            parts.append(f"Clip action prompt: {segment['video_prompt']}")
        elif segment.get("description"):
            parts.append(f"Clip action prompt: {segment['description']}")
        if segment.get("continuity_from_prev"):
            parts.append(f"Previous tail-frame continuity to preserve: {segment['continuity_from_prev']}")
        if segment.get("continuity_to_next"):
            parts.append(f"Target ending state for next clip handoff: {segment['continuity_to_next']}")
        if segment.get("prefer_character_handoff_end_frame"):
            handoff_character_ids = list(segment.get("handoff_character_profile_ids") or [])
            if handoff_character_ids:
                parts.append(
                    "Finish the clip with these continuing characters still clearly visible in the final frame for the next clip handoff: "
                    + ", ".join(str(item) for item in handoff_character_ids if str(item).strip())
                )
            else:
                parts.append(
                    "Finish the clip with the continuing on-screen characters still clearly visible in the final frame for the next clip handoff"
                )
        elif segment.get("prefer_primary_character_end_frame"):
            parts.append(
                "Finish the clip with the main on-screen character still clearly visible in the final frame so the next clip can inherit stable identity and pose continuity"
            )
        parts.append("Preserve character face, hairstyle, outfit, color palette, and environment logic consistently across the whole clip")
        return ". ".join(part for part in parts if part).strip()

    def _build_segment_negative_prompt(
        self,
        *,
        segment: Dict[str, Any],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
    ) -> str:
        segment_characters, segment_scene = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )
        negatives: List[str] = []
        if segment.get("negative_prompt"):
            negatives.append(str(segment.get("negative_prompt")).strip())
        for profile in segment_characters:
            if profile.get("negative_prompt"):
                negatives.append(str(profile.get("negative_prompt")).strip())
            forbidden_traits = profile.get("forbidden_traits") or []
            if forbidden_traits:
                negatives.extend(str(item).strip() for item in forbidden_traits if str(item).strip())
        if segment_scene and segment_scene.get("negative_prompt"):
            negatives.append(str(segment_scene.get("negative_prompt")).strip())
        if segment_scene:
            forbidden_elements = segment_scene.get("forbidden_elements") or segment_scene.get("props_forbidden") or []
            negatives.extend(str(item).strip() for item in forbidden_elements if str(item).strip())
        return ", ".join(item for item in negatives if item)

    def _build_provider_image_reference(self, asset_url: str) -> Optional[str]:
        if not asset_url:
            return None
        if asset_url.startswith("http://") or asset_url.startswith("https://"):
            return asset_url

        asset_path = self._asset_url_to_path(asset_url)
        if not asset_path or not asset_path.exists():
            return None

        mime_type = "image/png"
        suffix = asset_path.suffix.lower()
        if suffix == ".jpg" or suffix == ".jpeg":
            mime_type = "image/jpeg"
        elif suffix == ".webp":
            mime_type = "image/webp"
        elif suffix == ".svg":
            mime_type = "image/svg+xml"

        encoded = base64.b64encode(asset_path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _build_kling_image_reference(self, asset_url: str) -> Optional[str]:
        if not asset_url:
            return None
        if asset_url.startswith("http://") or asset_url.startswith("https://"):
            return asset_url

        asset_path = self._asset_url_to_path(asset_url)
        if not asset_path or not asset_path.exists():
            return None

        return base64.b64encode(asset_path.read_bytes()).decode("utf-8")

    def _build_kling_image_list(
        self,
        *,
        task_dir: Optional[Path],
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        segment_characters, _ = self._get_segment_profile_context(
            segment=segment,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
        )

        candidates: List[str] = []
        if keyframe_bundle:
            start_frame = str((keyframe_bundle.get("start_frame") or {}).get("asset_url") or "").strip()
            if start_frame:
                candidates.append(start_frame)

        for item in self._build_video_character_reference_images(
            task_dir=task_dir,
            segment=segment,
            character_profiles=segment_characters,
        ):
            asset_url = str(item.get("url") or "").strip()
            if asset_url:
                candidates.append(asset_url)

        image_list: List[Dict[str, str]] = []
        seen = set()
        for asset_url in candidates:
            payload = self._build_kling_image_reference(asset_url)
            if not payload or payload in seen:
                continue
            seen.add(payload)
            image_list.append({"image": payload})
            if len(image_list) >= 4:
                break
        return image_list

    def _resolve_kling_model(self, requested_model: str) -> str:
        normalized = str(requested_model or "").strip()
        if normalized.startswith("kling-"):
            return normalized
        return str(getattr(settings, "KLING_VIDEO_MODEL", "") or "kling-v1-6")

    def _resolve_kling_mode(self) -> str:
        mode = str(getattr(settings, "KLING_VIDEO_MODE", "") or "std").strip().lower()
        return mode if mode in {"std", "pro"} else "std"

    def _normalize_kling_aspect_ratio(self, value: str) -> str:
        allowed = {"16:9", "9:16", "1:1"}
        return value if value in allowed else "16:9"

    def _normalize_kling_duration(self, value: Any) -> int:
        try:
            rounded = int(round(float(value)))
        except (TypeError, ValueError):
            rounded = 5
        if rounded <= 5:
            return 5
        return min(int(getattr(settings, "KLING_MAX_DURATION", 10) or 10), 10)

    def _normalize_doubao_resolution(self, value: str) -> str:
        allowed = {"480p", "720p", "1080p"}
        return value if value in allowed else "720p"

    def _normalize_doubao_aspect_ratio(self, value: str) -> str:
        allowed = {"16:9", "4:3", "1:1", "9:16", "21:9"}
        return value if value in allowed else "16:9"

    def _normalize_doubao_duration(
        self,
        *,
        duration: float,
        model_name: str = "",
        content: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        rounded = int(round(max(2.0, min(float(duration or 5), MAX_VIDEO_SEGMENT_DURATION))))
        has_image_input = any((item or {}).get("type") == "image_url" for item in (content or []))

        if has_image_input:
            snapped = 5 if rounded <= 7 else 10
            if snapped != rounded:
                logger.info(
                    "Normalize i2v duration for model %s from %ss to %ss",
                    model_name or "<unknown>",
                    rounded,
                    snapped,
                )
            return snapped

        return max(2, min(int(MAX_VIDEO_SEGMENT_DURATION), rounded))

    def _normalize_service_tier(self, value: str) -> str:
        return value if value in {"default", "flex"} else "default"

    def _normalize_provider_seed(self, value: Any) -> int:
        if value in (None, "", "null"):
            return -1
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def _map_resolution(self, value: str, enum_cls: Any) -> Any:
        mapping = {
            "480p": getattr(enum_cls, "R_480P", None),
            "540p": getattr(enum_cls, "R_540P", getattr(enum_cls, "R_480P", None)),
            "720p": getattr(enum_cls, "R_720P", None),
            "1080p": getattr(enum_cls, "R_1080P", getattr(enum_cls, "R_720P", None)),
        }
        return mapping.get(value, next(iter(mapping.values())))

    def _map_aspect_ratio(self, value: str, enum_cls: Any) -> Any:
        mapping = {
            "16:9": getattr(enum_cls, "RATIO_16_9", getattr(enum_cls, "R_16_9", None)),
            "9:16": getattr(enum_cls, "RATIO_9_16", getattr(enum_cls, "R_9_16", None)),
            "1:1": getattr(enum_cls, "RATIO_1_1", getattr(enum_cls, "R_1_1", None)),
            "4:3": getattr(enum_cls, "RATIO_4_3", getattr(enum_cls, "R_4_3", None)),
        }
        return mapping.get(value, next(iter(mapping.values())))

    def _map_duration(self, duration: float, enum_cls: Any) -> Any:
        if duration <= 5:
            return getattr(enum_cls, "DUR_5S")
        if duration <= 10:
            return getattr(enum_cls, "DUR_10S")
        return getattr(enum_cls, "DUR_10S")

    def _load_local_image(self, asset_url: str) -> Optional[Any]:
        try:
            from PIL import Image

            asset_path = self._asset_url_to_path(asset_url)
            if asset_path and asset_path.exists():
                return Image.open(asset_path)
        except Exception:
            return None
        return None

    def _build_asset_url(self, output_path: Path) -> str:
        relative_path = output_path.relative_to(Path(settings.UPLOAD_DIR))
        return f"/uploads/{relative_path.as_posix()}"

    def _asset_url_to_path(self, asset_url: str) -> Optional[Path]:
        if not asset_url:
            return None
        if asset_url.startswith("/uploads/"):
            relative_path = asset_url.replace("/uploads/", "", 1)
            return Path(settings.UPLOAD_DIR) / relative_path
        return None

    def _build_optional_asset_url(self, asset_path: Optional[str]) -> str:
        if not asset_path:
            return ""
        path = Path(str(asset_path)).expanduser()
        if not path.exists():
            return ""
        try:
            return self._build_asset_url(path)
        except Exception:
            return ""

    def _extract_media_duration(self, final_output: Dict[str, Any]) -> Optional[float]:
        video_info = dict(final_output.get("video_info") or {})
        format_info = dict(video_info.get("format") or {})
        try:
            duration = float(format_info.get("duration") or 0.0)
        except (TypeError, ValueError):
            return None
        return duration if duration > 0 else None

    def _should_reuse_previous_last_frame(self, bundle: Optional[Dict[str, Any]]) -> bool:
        start_frame = dict((bundle or {}).get("start_frame") or {})
        if str(start_frame.get("asset_url") or "").strip():
            return False
        source = str(start_frame.get("source") or "").strip()
        return source in {"", "runtime-last-frame", "previous-render-last-frame"}

    def _with_runtime_start_frame(
        self,
        *,
        bundle: Optional[Dict[str, Any]],
        segment: Dict[str, Any],
        start_frame: KeyframeAsset,
    ) -> Dict[str, Any]:
        normalized = self._normalize_keyframe_bundle(
            bundle or {
                "segment_number": segment["segment_number"],
                "title": segment["title"],
            },
            int(segment["segment_number"]) - 1,
        )
        normalized["start_frame"] = asdict(
            KeyframeAsset(
                asset_url=start_frame.asset_url,
                asset_type=start_frame.asset_type,
                asset_filename=start_frame.asset_filename,
                prompt=start_frame.prompt,
                source="previous-render-last-frame",
                status="completed",
                notes="渲染时复用上一片段返回的尾帧作为当前片段首帧",
            )
        )
        return normalized

    def _build_runtime_last_frame_asset(
        self,
        *,
        clip_number: int,
        segment_title: str,
        clip_asset: Dict[str, Any],
    ) -> Optional[KeyframeAsset]:
        last_frame_url = str(clip_asset.get("last_frame_url") or "").strip()
        if not last_frame_url:
            return None
        return KeyframeAsset(
            asset_url=last_frame_url,
            asset_type="image/png",
            asset_filename=f"clip_{clip_number:02d}_last_frame.png",
            prompt=f"{segment_title} 尾帧（由豆包视频接口返回）",
            source="provider-return-last-frame",
            status="completed",
            notes="该尾帧将自动用于下一片段首帧输入",
        )

    def _sync_runtime_keyframe_state(
        self,
        *,
        state: RenderTaskState,
        clip_number: int,
        start_frame: Optional[KeyframeAsset] = None,
        end_frame: Optional[KeyframeAsset] = None,
    ) -> None:
        for bundle in state.keyframes:
            if int(bundle.get("segment_number") or 0) != clip_number:
                continue
            if start_frame:
                bundle["start_frame"] = asdict(start_frame)
            if end_frame:
                bundle["end_frame"] = asdict(end_frame)
            break

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", value).strip("_")
        return slug or "project"

    def _wrap_lines(self, text: str, *, width: int) -> List[str]:
        normalized = " ".join(text.split())
        return textwrap.wrap(normalized, width=width) if normalized else [""]


pipeline_workflow_service = PipelineWorkflowService()
