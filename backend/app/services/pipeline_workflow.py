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

from app.core.config import settings
from app.services.script_generator import FullScript, ScriptGenerator
from app.services.script_splitter import ScriptSplitter, SplitConfig
from app.services.video_merger import MergeOptions, VideoMergerService, VideoSegment as MergedVideoSegment

logger = logging.getLogger(__name__)


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
        return {
            "task_id": self.task_id,
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
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PipelineWorkflowService:
    """单主链路工作流服务。"""

    def __init__(self) -> None:
        self.generator = ScriptGenerator()
        self.tasks: Dict[str, RenderTaskState] = {}
        self.output_root = Path(settings.UPLOAD_DIR) / "generated" / "pipeline"
        self.reference_root = Path(settings.UPLOAD_DIR) / "generated" / "references"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.reference_root.mkdir(parents=True, exist_ok=True)

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

        asset = ReferenceAsset(
            id=asset_id,
            url=self._build_asset_url(target_path),
            filename=safe_filename,
            original_filename=filename,
            content_type=content_type,
            size=len(content),
            source="upload",
        )
        return asdict(asset)

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
    ) -> Dict[str, Any]:
        """生成完整剧本，并转换成可编辑文本。"""
        resolved_character_profiles = self._resolve_character_profiles(
            selected_character_ids=selected_character_ids or [],
            character_profiles=character_profiles or [],
        )
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
        splitter = ScriptSplitter(
            SplitConfig(
                max_segment_duration=max_segment_duration,
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

        for index, segment in enumerate(normalized_segments):
            if index == 0:
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
                start_notes = "首段首帧由 NanoBanana/参考图生成，作为整条视频的起始画面"
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

        return {
            "success": True,
            "message": "已生成首段首帧，后续片段将在渲染时自动串联上一段尾帧",
            "project_title": project_title or "未命名项目",
            "style": style,
            "selected_character_ids": [profile["id"] for profile in resolved_character_profiles if profile.get("id")],
            "selected_scene_ids": [profile["id"] for profile in resolved_scene_profiles if profile.get("id")],
            "character_profiles": resolved_character_profiles,
            "scene_profiles": resolved_scene_profiles,
            "reference_images": normalized_references,
            "keyframes": [asdict(bundle) for bundle in keyframe_bundles],
        }

    def create_render_task(
        self,
        *,
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
        task_id = uuid.uuid4().hex
        renderer = self._choose_render_provider(config)

        state = RenderTaskState(
            task_id=task_id,
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
        return state

    async def run_render_task(self, task_id: str) -> None:
        """执行片段渲染与最终合成。"""
        state = self.tasks[task_id]
        state.status = "processing"
        state.current_step = "开始生成视频片段"
        state.progress = 5.0
        state.touch()

        task_dir = self.output_root / task_id / "render"
        task_dir.mkdir(parents=True, exist_ok=True)

        keyframe_map = {
            int(bundle["segment_number"]): bundle
            for bundle in state.keyframes
        }
        previous_last_frame: Optional[KeyframeAsset] = None

        try:
            total_segments = len(state.segments)
            for index, segment in enumerate(state.segments):
                clip_number = segment["segment_number"]
                state.current_step = f"生成片段 {clip_number}/{total_segments}"
                state.progress = 5.0 + (index / max(total_segments, 1)) * 75.0
                state.touch()

                runtime_bundle = keyframe_map.get(clip_number)
                if previous_last_frame:
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

                state.clips[index].status = "completed"
                state.clips[index].asset_url = clip_asset["asset_url"]
                state.clips[index].asset_type = clip_asset["asset_type"]
                state.clips[index].asset_filename = clip_asset["asset_filename"]
                state.clips[index].provider = clip_asset.get("provider", "")
                if clip_asset.get("provider") == "doubao-official-text-only":
                    warning = f"片段 {clip_number} 因参考图被风控，已降级为豆包纯文本视频生成"
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

                await asyncio.sleep(0.05)

            state.current_step = "合并最终成片"
            state.progress = 85.0
            state.touch()

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

            state.final_output = final_output
            state.status = "completed"
            state.progress = 100.0
            state.current_step = "完成"
            state.touch()
        except Exception as exc:
            logger.error("Render task failed: %s", exc, exc_info=True)
            state.status = "failed"
            state.error = str(exc)
            state.current_step = "失败"
            state.touch()

    def get_render_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态。"""
        state = self.tasks.get(task_id)
        return state.to_dict() if state else None

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
        return {
            "segment_number": int(segment.get("segment_number") or index + 1),
            "title": str(segment.get("title") or f"片段 {index + 1}"),
            "description": str(segment.get("description") or ""),
            "start_time": float(segment.get("start_time") or 0.0),
            "end_time": float(segment.get("end_time") or 0.0),
            "duration": float(segment.get("duration") or 5.0),
            "shots_summary": str(segment.get("shots_summary") or ""),
            "key_actions": list(segment.get("key_actions") or []),
            "key_dialogues": list(segment.get("key_dialogues") or []),
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
            "video_url": str(segment.get("video_url") or ""),
            "status": str(segment.get("status") or "ready"),
        }

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
        prompt = self._build_keyframe_prompt(
            segment=segment,
            frame_kind=frame_kind,
            style=style,
            character_profiles=character_profiles,
            scene_profiles=scene_profiles,
            reference_images=reference_images,
        )

        nanobanana_api_key = getattr(settings, "NANOBANANA_API_KEY", None) or os.getenv("NANOBANANA_API_KEY")
        if nanobanana_api_key:
            generated = await asyncio.to_thread(
                self._generate_keyframe_with_nanobanana,
                task_dir,
                segment,
                frame_kind,
                prompt,
                reference_images,
                base_asset,
            )
            if generated:
                return generated

            logger.warning(
                "NanoBanana keyframe generation returned no asset for segment=%s frame=%s, fallback to placeholder",
                segment["segment_number"],
                frame_kind,
            )
        else:
            logger.warning(
                "NANOBANANA_API_KEY not configured, fallback to placeholder keyframe for segment=%s frame=%s",
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

    def _generate_keyframe_with_nanobanana(
        self,
        task_dir: Path,
        segment: Dict[str, Any],
        frame_kind: str,
        prompt: str,
        reference_images: List[Dict[str, Any]],
        base_asset: Optional[KeyframeAsset],
    ) -> Optional[KeyframeAsset]:
        try:
            from app.services.nanobanana_pro import NanoBananaProClient

            client = NanoBananaProClient(
                api_key=getattr(settings, "NANOBANANA_API_KEY", None) or os.getenv("NANOBANANA_API_KEY"),
                api_url=getattr(settings, "NANOBANANA_BASE_URL", None),
            )
            reference_paths = self._existing_reference_paths(reference_images)
            base_path = self._asset_url_to_path(base_asset.asset_url) if base_asset else None

            if base_path and base_path.exists():
                result = client.generate_image_to_image(str(base_path), prompt, aspect_ratio="16:9", image_size="2k")
                source = "nanobanana-image-to-image"
            elif len(reference_paths) > 1:
                result = client.generate_multi_image_mix([str(path) for path in reference_paths], prompt, aspect_ratio="16:9", image_size="2k")
                source = "nanobanana-multi-image-mix"
            elif len(reference_paths) == 1:
                result = client.generate_image_to_image(str(reference_paths[0]), prompt, aspect_ratio="16:9", image_size="2k")
                source = "nanobanana-image-to-image"
            else:
                result = client.generate_text_to_image(prompt, aspect_ratio="16:9", image_size="2k")
                source = "nanobanana-text-to-image"

            if not result.get("success") or not result.get("image_data"):
                logger.warning("NanoBanana keyframe generation failed: %s", result.get("error"))
                return None

            return self._store_binary_image(
                task_dir=task_dir,
                filename=f"segment_{segment['segment_number']:02d}_{frame_kind}.png",
                content=result["image_data"],
                prompt=prompt,
                source=source,
            )
        except Exception as exc:
            logger.warning("NanoBanana unavailable, fallback to placeholder: %s", exc)
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
        return KeyframeAsset(
            asset_url=self._build_asset_url(output_path),
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
            character_text = "Character base: " + " | ".join(
                self._build_character_image_base(profile) for profile in segment_characters[:4]
            ) + ". "
        scene_text = ""
        if segment_scene:
            scene_text = f"Scene base: {self._build_scene_image_base(segment_scene)}. "
        style_text = f"Visual style: {style}. " if style else ""
        reference_text = (
            "Keep subject appearance, costume, environment layout, lighting mood, and spatial atmosphere consistent with the provided reference images. "
            if reference_images
            else ""
        )
        frame_goal = "opening shot, establish pose, camera-ready composition" if frame_kind == "start" else "ending shot, preserve continuity, prepare next segment entry"
        prompt_focus = str(segment.get("prompt_focus") or "")
        continuity_text = str(segment.get("continuity_to_next") if frame_kind == "end" else segment.get("continuity_from_prev") or "")
        hard_constraints = self._build_segment_hard_constraints(segment_characters, segment_scene)
        return (
            f"{character_text}{scene_text}{style_text}{reference_text}"
            f"{segment['video_prompt'] or segment['description']}. "
            f"{f'Key focus: {prompt_focus}. ' if prompt_focus else ''}"
            f"{f'Continuity note: {continuity_text}. ' if continuity_text else ''}"
            f"{hard_constraints}"
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

        return {
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
            "created_at": str(profile.get("created_at") or now),
            "updated_at": str(profile.get("updated_at") or profile.get("created_at") or now),
        }

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
        if requested in {"doubao", "auto"}:
            if self._doubao_enabled():
                return "doubao-official"
            raise RuntimeError("未配置豆包视频生成能力，请补充 DOUBAO_API_KEY 或显式选择 local 预览模式")
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
        if provider == "doubao-official":
            rendered = await self._try_render_doubao_video(
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
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        if not self._doubao_enabled():
            raise RuntimeError("DOUBAO_API_KEY 未配置，无法调用豆包视频生成")

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
                            segment=segment,
                            keyframe_bundle=None,
                            character_profiles=character_profiles,
                            scene_profiles=scene_profiles,
                            render_config=render_config,
                        )
                        response = await generator.create_video_task(
                            content=text_only_content,
                            **request_kwargs,
                        )
                    else:
                        raise
                if response.status in {"pending", "processing", "queued", "running"}:
                    response = await generator.wait_for_completion(response.id, poll_interval=5, max_wait_time=900)
            finally:
                await generator.close()

            if response.video_url:
                asset_filename = f"clip_{segment['segment_number']:02d}.mp4"
                return {
                    "asset_url": response.video_url,
                    "asset_type": "video/mp4",
                    "asset_filename": asset_filename,
                    "provider": "doubao-official-text-only" if used_text_only_retry else "doubao-official",
                    "last_frame_url": response.last_frame_url or "",
                }
            raise RuntimeError(f"片段 {segment['segment_number']} 未返回 video_url")
        except Exception as exc:
            logger.error("Doubao render failed for segment %s: %s", segment.get("segment_number"), exc)
            raise RuntimeError(f"片段 {segment['segment_number']} 豆包视频生成失败: {exc}") from exc

    def _is_sensitive_image_error(self, exc: Exception) -> bool:
        if not isinstance(exc, httpx.HTTPStatusError) or exc.response is None:
            return False
        try:
            payload = exc.response.json()
        except Exception:
            return False
        error = payload.get("error") or {}
        return error.get("code") == "InputImageSensitiveContentDetected"

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
        if not merger.ffmpeg_available:
            raise RuntimeError("FFmpeg unavailable")

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

    def _doubao_enabled(self) -> bool:
        return bool(self._get_doubao_api_key())

    def _get_doubao_api_key(self) -> Optional[str]:
        return settings.DOUBAO_API_KEY or os.getenv("DOUBAO_API_KEY")

    def _normalize_render_config(self, render_config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": str(render_config.get("provider") or "auto"),
            "resolution": self._normalize_doubao_resolution(str(render_config.get("resolution") or "720p")),
            "aspect_ratio": self._normalize_doubao_aspect_ratio(str(render_config.get("aspect_ratio") or "16:9")),
            "watermark": bool(render_config.get("watermark", False)),
            "provider_model": str(render_config.get("provider_model") or settings.DOUBAO_VIDEO_MODEL),
            "camera_fixed": bool(render_config.get("camera_fixed", False)),
            "generate_audio": bool(render_config.get("generate_audio", True)),
            "return_last_frame": True,
            "service_tier": self._normalize_service_tier(str(render_config.get("service_tier") or "default")),
            "seed": self._normalize_provider_seed(render_config.get("seed")),
        }

    def _build_doubao_content(
        self,
        *,
        segment: Dict[str, Any],
        keyframe_bundle: Optional[Dict[str, Any]],
        character_profiles: List[Dict[str, Any]],
        scene_profiles: List[Dict[str, Any]],
        render_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
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
        if keyframe_bundle:
            start_frame = (keyframe_bundle.get("start_frame") or {}).get("asset_url") or ""

        if start_frame:
            logger.info(
                "Using single start frame for segment %s; next clip start will come from provider returned last frame",
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
                f"Keep the motion and character identity consistent with the provided first-frame image. "
                f"The final moment should land on this target ending state: {final_moment_hint}."
            )

        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        if not keyframe_bundle:
            return content

        for image_url in [start_frame]:
            provider_image_url = self._build_provider_image_reference(str(image_url))
            if provider_image_url:
                content.append({"type": "image_url", "image_url": {"url": provider_image_url}})

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
        return filtered_characters or character_profiles[:4], filtered_scene

    def _build_character_image_base(self, profile: Dict[str, Any]) -> str:
        return "；".join(
            part
            for part in [
                str(profile.get("name") or "").strip(),
                str(profile.get("image_prompt_base") or "").strip(),
                str(profile.get("core_appearance") or "").strip(),
                str(profile.get("outfit") or "").strip(),
                str(profile.get("gear") or "").strip(),
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
        return "；".join(
            part
            for part in [
                str(profile.get("name") or "").strip(),
                str(profile.get("video_prompt_base") or "").strip(),
                str(profile.get("speaking_style") or "").strip(),
                str(profile.get("common_actions") or "").strip(),
            ]
            if part
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
        for profile in character_profiles[:3]:
            must_keep = profile.get("must_keep") or []
            if must_keep:
                constraints.append(f"Keep {profile.get('name')}: {', '.join(must_keep)}")
        if scene_profile:
            must_have = scene_profile.get("must_have_elements") or scene_profile.get("props_must_have") or []
            if must_have:
                constraints.append(f"Scene must include: {', '.join(must_have)}")
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
            parts.append("Character continuity: " + " | ".join(self._build_character_video_base(item) for item in segment_characters[:4]))
        if segment_scene:
            parts.append("Scene continuity: " + self._build_scene_video_base(segment_scene))
        if segment.get("prompt_focus"):
            parts.append(f"Current clip focus: {segment['prompt_focus']}")
        if segment.get("shots_summary"):
            parts.append(f"Shot chain: {segment['shots_summary']}")
        if segment.get("video_prompt"):
            parts.append(f"Clip action prompt: {segment['video_prompt']}")
        elif segment.get("description"):
            parts.append(f"Clip action prompt: {segment['description']}")
        if segment.get("continuity_from_prev"):
            parts.append(f"Continuity from previous: {segment['continuity_from_prev']}")
        if segment.get("continuity_to_next"):
            parts.append(f"Landing for next clip: {segment['continuity_to_next']}")
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
        if segment_scene and segment_scene.get("negative_prompt"):
            negatives.append(str(segment_scene.get("negative_prompt")).strip())
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
        rounded = int(round(float(duration or 5)))
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

        return max(2, min(12, rounded))

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
        if duration <= 15:
            return getattr(enum_cls, "DUR_15S")
        return getattr(enum_cls, "DUR_20S")

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
