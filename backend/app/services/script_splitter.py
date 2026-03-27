#!/usr/bin/env python3
"""
剧本拆分服务 - 将完整剧本拆分为多个短视频片段

核心功能：
1. 智能时长分析 - 根据剧本内容计算所需总时长
2. 剧情断点检测 - 在合适的位置拆分剧本
3. 衔接点管理 - 确保片段按时间连续衔接，不做重叠切片
4. 视频Prompt生成 - 为每个片段生成视频生成提示词

使用：
    from app.services.script_splitter import split_script
    
    result = await split_script(full_script_text, max_segment_duration=10.0)
    
    for segment in result.segments:
        print(f"片段 {segment.segment_number}: {segment.duration}秒")
        print(f"Prompt: {segment.video_prompt}")
"""

import ast
import re
import json
import asyncio
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime
import logging

from app.services.doubao_llm import DoubaoLLM, DoubaoMessage

logger = logging.getLogger(__name__)

MAX_VIDEO_SEGMENT_DURATION = 10.0


@dataclass
class VideoSegment:
    """视频片段（拆分后的结果）"""
    segment_number: int                    # 片段序号
    title: str = ""                       # 片段标题
    description: str = ""                 # 片段描述
    
    # 时长信息
    start_time: float = 0.0                # 在整体剧本中的开始时间
    end_time: float = 0.0                  # 在整体剧本中的结束时间
    duration: float = 0.0                  # 时长
    
    # 内容概要
    shots_summary: str = ""               # 分镜概要
    key_actions: List[str] = field(default_factory=list)  # 关键动作
    key_dialogues: List["SegmentDialogue"] = field(default_factory=list)  # 关键对话
    
    # 衔接信息
    transition_in: str = ""               # 进入过渡效果
    transition_out: str = ""              # 退出过渡效果
    continuity_from_prev: str = ""        # 与前一片段的连续性
    continuity_to_next: str = ""          # 与后一片段的连续性
    
    # 视频生成配置
    video_prompt: str = ""                # 视频生成提示词
    negative_prompt: str = ""             # 负面提示词
    generation_config: Dict[str, Any] = field(default_factory=dict)
    scene_profile_id: str = ""
    scene_profile_version: int = 1
    character_profile_ids: List[str] = field(default_factory=list)
    character_profile_versions: Dict[str, int] = field(default_factory=dict)
    prompt_focus: str = ""
    contains_primary_character: bool = False
    ending_contains_primary_character: bool = False
    pre_generate_start_frame: bool = False
    start_frame_generation_reason: str = ""
    prefer_primary_character_end_frame: bool = False
    new_character_profile_ids: List[str] = field(default_factory=list)
    late_entry_character_profile_ids: List[str] = field(default_factory=list)
    handoff_character_profile_ids: List[str] = field(default_factory=list)
    ending_contains_handoff_characters: bool = False
    prefer_character_handoff_end_frame: bool = False
    
    # 结果
    video_url: str = ""                   # 生成的视频URL
    status: str = "pending"               # 状态
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)


@dataclass
class SplitConfig:
    """剧本拆分配置"""
    max_segment_duration: float = MAX_VIDEO_SEGMENT_DURATION     # 每个片段最大时长（秒）
    min_segment_duration: float = 3.0      # 每个片段最小时长（秒）
    prefer_scene_boundary: bool = True    # 优先在场景边界处拆分
    preserve_dialogue: bool = True        # 保持对话完整性
    smooth_transition: bool = True        # 启用平滑过渡


@dataclass
class SplitResult:
    """剧本拆分结果"""
    original_script: str = ""             # 原始剧本
    total_duration: float = 0.0            # 总时长
    segment_count: int = 0                 # 片段数量
    segments: List[VideoSegment] = field(default_factory=list)
    config: SplitConfig = field(default_factory=SplitConfig)
    
    # 衔接点信息
    continuity_points: List[Dict[str, Any]] = field(default_factory=list)
    validation_report: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "original_script": self.original_script[:200] + "..." if len(self.original_script) > 200 else self.original_script,
            "total_duration": self.total_duration,
            "segment_count": self.segment_count,
            "segments": [
                {
                    "segment_number": seg.segment_number,
                    "title": seg.title,
                    "duration": seg.duration,
                    "video_prompt": seg.video_prompt[:100] + "..." if len(seg.video_prompt) > 100 else seg.video_prompt,
                    "status": seg.status
                }
                for seg in self.segments
            ],
            "continuity_points": self.continuity_points,
            "validation_report": self.validation_report,
        }


@dataclass
class ParsedShot:
    """从完整剧本文本中解析出的镜头块。"""
    scene_number: int
    scene_title: str
    scene_type: str
    scene_profile_id: str
    scene_profile_version: int
    location: str
    time_label: str
    atmosphere: str
    shot_number: int
    duration: float
    prompt_focus: str = ""
    shot_type: str = ""
    camera_angle: str = ""
    camera_movement: str = ""
    description: str = ""
    environment: str = ""
    lighting: str = ""
    characters_in_shot: List[str] = field(default_factory=list)
    character_profile_ids: List[str] = field(default_factory=list)
    character_profile_versions: Dict[str, int] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    dialogues: List[str] = field(default_factory=list)
    sound_effects: List[str] = field(default_factory=list)
    music: str = ""
    raw_lines: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class SegmentDialogue:
    text: str
    speaker_name: str = ""
    speaker_character_id: str = ""
    emotion: str = ""
    tone: str = ""


class ScriptSplitter:
    """
    剧本拆分器 - 核心类
    负责将长剧本智能拆分为多个短视频片段
    """
    
    def __init__(self, config: Optional[SplitConfig] = None):
        self.config = config or SplitConfig()
        self.config.max_segment_duration = min(float(self.config.max_segment_duration), MAX_VIDEO_SEGMENT_DURATION)
        self.llm = DoubaoLLM()
    
    async def split_script(
        self,
        script: str,
        target_duration: Optional[float] = None
    ) -> SplitResult:
        """
        拆分剧本
        
        Args:
            script: 完整剧本文本（已包含详细的分镜、对话等）
            target_duration: 目标总时长（可选）
            
        Returns:
            SplitResult: 拆分结果
        """
        logger.info(f"开始拆分剧本，目标时长: {target_duration or '自动'}")
        
        # 步骤1: 使用LLM分析剧本结构并确定拆分点
        logger.info("步骤1: 分析剧本结构...")
        analysis = await self._analyze_script(script)
        
        # 步骤2: 计算拆分点
        logger.info("步骤2: 规划拆分点...")
        effective_target_duration = target_duration or analysis.get("total_duration", 60.0)
        split_points = await self._plan_segments_with_llm(
            script=script,
            analysis=analysis,
            target_duration=effective_target_duration,
        )
        if not split_points:
            logger.warning("LLM 分段规划失败，回退本地拆分策略")
            split_points = self._calculate_split_points(
                analysis,
                effective_target_duration,
            )

        split_points = self._rebalance_split_points(
            split_points=split_points,
            parsed_shots=analysis.get("parsed_shots", []) or [],
            target_duration=effective_target_duration,
        )
        split_points = self._optimize_split_points_for_character_continuity(
            split_points=split_points,
            parsed_shots=analysis.get("parsed_shots", []) or [],
            target_duration=effective_target_duration,
        )
        split_points = self._optimize_split_points_for_first_frame_character_stability(
            split_points=split_points,
            parsed_shots=analysis.get("parsed_shots", []) or [],
            target_duration=effective_target_duration,
        )
        
        # 步骤3: 生成分段
        logger.info("步骤3: 生成视频片段...")
        segments = await self._generate_segments(script, split_points)
        segments = self._annotate_segments_for_video_generation(
            segments=segments,
            parsed_shots=analysis.get("parsed_shots", []) or [],
        )

        # 步骤4: 生成衔接信息
        logger.info("步骤4: 生成衔接信息...")
        continuity_points = self._generate_continuity_points(segments)

        # 步骤5: 对拆分结果做二次校验
        logger.info("步骤5: 校验视频片段...")
        validation_report = await self._review_segments(
            script=script,
            segments=segments,
            target_duration=target_duration,
        )

        # 步骤6: 自动修复校验发现的问题，并返回修复后的更优结果
        logger.info("步骤6: 修复视频片段问题...")
        segments, continuity_points, validation_report = await self._auto_fix_segments_if_needed(
            script=script,
            analysis=analysis,
            effective_target_duration=effective_target_duration,
            current_split_points=split_points,
            current_segments=segments,
            current_continuity_points=continuity_points,
            current_validation_report=validation_report,
            requested_target_duration=target_duration,
        )
        # 组装结果
        total_duration = sum(seg.duration for seg in segments)
        result = SplitResult(
            original_script=script,
            total_duration=total_duration,
            segment_count=len(segments),
            segments=segments,
            config=self.config,
            continuity_points=continuity_points,
            validation_report=validation_report,
        )
        
        logger.info(f"剧本拆分完成，共 {len(segments)} 个片段，总时长 {total_duration:.1f}秒")
        
        return result
    
    async def _analyze_script(self, script: str) -> dict:
        """使用LLM分析剧本结构"""
        parsed_shots = self._parse_structured_script(script)
        if parsed_shots:
            total_duration = parsed_shots[-1].end_time
            scenes: List[Dict[str, Any]] = []
            scene_map: Dict[int, Dict[str, Any]] = {}
            for shot in parsed_shots:
                if shot.scene_number not in scene_map:
                    scene_map[shot.scene_number] = {
                        "scene_number": shot.scene_number,
                        "scene_type": shot.scene_type,
                        "scene_profile_id": shot.scene_profile_id,
                        "scene_profile_version": shot.scene_profile_version,
                        "start_time": shot.start_time,
                        "end_time": shot.end_time,
                        "description": shot.scene_title or shot.description,
                    }
                    scenes.append(scene_map[shot.scene_number])
                else:
                    scene_map[shot.scene_number]["end_time"] = shot.end_time

            recommended_split_points: List[float] = []
            current_duration = 0.0
            last_scene_number: Optional[int] = None
            for shot in parsed_shots:
                if (
                    last_scene_number is not None
                    and shot.scene_number != last_scene_number
                    and current_duration >= self.config.min_segment_duration
                ):
                    recommended_split_points.append(round(shot.start_time, 2))
                    current_duration = 0.0

                current_duration += shot.duration
                if current_duration >= self.config.max_segment_duration:
                    recommended_split_points.append(round(shot.end_time, 2))
                    current_duration = 0.0

                last_scene_number = shot.scene_number

            deduped_points: List[float] = []
            for point in recommended_split_points:
                if point <= 0 or point >= total_duration:
                    continue
                if not deduped_points or abs(deduped_points[-1] - point) > 0.01:
                    deduped_points.append(point)

            return {
                "total_duration": total_duration,
                "scenes": scenes,
                "key_moments": [],
                "recommended_split_points": deduped_points,
                "parsed_shots": parsed_shots,
            }
        
        system_prompt = """你是一位专业的剧本分析师，擅长分析剧本结构、识别剧情断点、计算时长。

请分析输入的剧本，提取以下信息：
1. 总时长估算（基于分镜时长）
2. 场景列表（每个场景的开始时间、结束时间、类型）
3. 关键剧情点（高潮、转折等及其时间点）
4. 推荐的拆分点（每10秒左右一个，优先在剧情断点处）

输出JSON格式：
{
    "total_duration": 45.5,
    "scenes": [
        {
            "scene_number": 1,
            "scene_type": "intro",
            "start_time": 0,
            "end_time": 15,
            "description": "场景描述"
        }
    ],
    "key_moments": [
        {
            "time": 20,
            "type": "climax",
            "description": "高潮点描述"
        }
    ],
    "recommended_split_points": [10, 20, 30, 40]
}"""

        user_prompt = f"请分析以下剧本：\n\n{script[:3000]}..."  # 限制长度
        
        try:
            messages = [
                DoubaoMessage(role="system", content=system_prompt),
                DoubaoMessage(role="user", content=user_prompt)
            ]
            
            response = await self.llm.chat_completion(
                messages,
                temperature=0.7,
                max_tokens=2000
            )
            
            content = response.get_content()
            
            # 解析JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"剧本分析失败: {e}")
            # 返回默认分析
            return {
                "total_duration": 60.0,
                "scenes": [],
                "key_moments": [],
                "recommended_split_points": [10, 20, 30, 40, 50],
                "parsed_shots": [],
            }
    
    def _calculate_split_points(self, analysis: dict, target_duration: float) -> List[Dict]:
        """计算拆分点"""
        parsed_shots: List[ParsedShot] = analysis.get("parsed_shots", []) or []
        if parsed_shots:
            split_points: List[Dict[str, Any]] = []
            current_shots: List[ParsedShot] = []
            current_duration = 0.0
            segment_number = 1

            def flush_segment() -> None:
                nonlocal current_shots, current_duration, segment_number
                if not current_shots:
                    return
                split_points.append({
                    "segment_number": segment_number,
                    "start_time": current_shots[0].start_time,
                    "end_time": current_shots[-1].end_time,
                    "duration": round(sum(shot.duration for shot in current_shots), 2),
                    "split_reason": "shot_timeline",
                    "scene_profile_id": current_shots[0].scene_profile_id,
                    "scene_profile_version": current_shots[0].scene_profile_version,
                    "shots": list(current_shots),
                })
                segment_number += 1
                current_shots = []
                current_duration = 0.0

            for shot in parsed_shots:
                if shot.start_time >= target_duration:
                    break

                shot_duration = shot.duration
                scene_changed = bool(current_shots and shot.scene_number != current_shots[-1].scene_number)
                exceeds_limit = bool(
                    current_shots
                    and current_duration + shot_duration > self.config.max_segment_duration
                    and current_duration >= self.config.min_segment_duration
                )

                if scene_changed and self.config.prefer_scene_boundary and current_duration >= self.config.min_segment_duration:
                    flush_segment()
                elif exceeds_limit:
                    flush_segment()

                current_shots.append(shot)
                current_duration += shot_duration

            flush_segment()
            return split_points
        
        split_points = []
        recommended = analysis.get("recommended_split_points", [])
        
        # 使用推荐的拆分点
        current_time = 0.0
        segment_number = 1
        
        for split_time in recommended:
            if split_time > target_duration:
                break
            
            duration = split_time - current_time
            if duration >= self.config.min_segment_duration:
                split_points.append({
                    "segment_number": segment_number,
                    "start_time": current_time,
                    "end_time": split_time,
                    "duration": duration,
                    "split_reason": "recommended_point"
                })
                segment_number += 1
                current_time = split_time
        
        # 添加最后一个片段
        if current_time < target_duration:
            final_duration = target_duration - current_time
            if final_duration >= self.config.min_segment_duration:
                split_points.append({
                    "segment_number": segment_number,
                    "start_time": current_time,
                    "end_time": target_duration,
                    "duration": final_duration,
                    "split_reason": "final_segment"
                })
        
        return split_points
    
    async def _generate_segments(self, script: str, split_points: List[Dict]) -> List[VideoSegment]:
        """生成视频片段"""
        
        segments = []
        character_registry = self._extract_character_registry(script)
        
        for i, point in enumerate(split_points):
            segment_shots: List[ParsedShot] = point.get("shots", []) or []
            # 提取该片段对应的剧本内容
            segment_script = self._extract_segment_script(
                script,
                point["start_time"],
                point["end_time"],
                segment_shots,
            )
            segment_character_ids = self._collect_unique_items(
                [profile_id for shot in segment_shots for profile_id in shot.character_profile_ids if profile_id],
                limit=12,
            )
            key_actions = self._collect_unique_items([action for shot in segment_shots for action in shot.actions], limit=6)
            key_dialogues = self._normalize_segment_dialogues(
                [dialogue for shot in segment_shots for dialogue in shot.dialogues],
                character_registry=character_registry,
                segment_character_ids=segment_character_ids,
                limit=4,
            )
            shots_summary = self._build_shots_summary(segment_shots)
            
            # 生成视频Prompt
            video_prompt = await self._generate_video_prompt(
                segment_script,
                point,
                segment_shots,
                i > 0,  # 不是第一个
                i < len(split_points) - 1  # 不是最后一个
            )
            
            title = str(point.get("title") or self._build_segment_title(point, segment_shots))
            description = str(
                point.get("description")
                or shots_summary
                or (segment_script[:200] + "..." if len(segment_script) > 200 else segment_script)
            )
            llm_key_actions = self._collect_unique_items(point.get("key_actions", []) or [], limit=6)
            llm_key_dialogues = self._normalize_segment_dialogues(
                point.get("key_dialogues", []) or [],
                character_registry=character_registry,
                segment_character_ids=segment_character_ids,
                limit=4,
            )
            # 创建片段
            segment = VideoSegment(
                segment_number=point["segment_number"],
                title=title,
                description=description,
                start_time=point["start_time"],
                end_time=point["end_time"],
                duration=point["duration"],
                shots_summary=shots_summary,
                key_actions=llm_key_actions or key_actions,
                key_dialogues=llm_key_dialogues or key_dialogues,
                video_prompt=video_prompt["prompt"],
                negative_prompt=video_prompt["negative_prompt"],
                generation_config=video_prompt.get("config", {}),
                continuity_from_prev=str(point.get("continuity_from_prev") or ("" if i == 0 else self._describe_transition_in(split_points[i - 1].get("shots", []), segment_shots))),
                continuity_to_next=str(point.get("continuity_to_next") or ("" if i == len(split_points) - 1 else self._describe_transition_out(segment_shots, split_points[i + 1].get("shots", [])))),
                scene_profile_id=str(point.get("scene_profile_id") or (segment_shots[0].scene_profile_id if segment_shots else "")),
                scene_profile_version=int(point.get("scene_profile_version") or (segment_shots[0].scene_profile_version if segment_shots else 1)),
                character_profile_ids=segment_character_ids,
                character_profile_versions=self._merge_profile_versions(segment_shots),
                prompt_focus=str(point.get("prompt_focus") or self._build_segment_prompt_focus(segment_shots)),
                contains_primary_character=bool(point.get("contains_primary_character", False)),
                ending_contains_primary_character=bool(point.get("ending_contains_primary_character", False)),
                pre_generate_start_frame=bool(point.get("pre_generate_start_frame", False)),
                start_frame_generation_reason=str(point.get("start_frame_generation_reason") or ""),
                prefer_primary_character_end_frame=bool(point.get("prefer_primary_character_end_frame", False)),
                new_character_profile_ids=list(point.get("new_character_profile_ids") or []),
                handoff_character_profile_ids=list(point.get("handoff_character_profile_ids") or []),
                ending_contains_handoff_characters=bool(point.get("ending_contains_handoff_characters", False)),
                prefer_character_handoff_end_frame=bool(point.get("prefer_character_handoff_end_frame", False)),
                status="ready"
            )
            
            segments.append(segment)
        
        return segments
    
    def _extract_segment_script(
        self,
        script: str,
        start_time: float,
        end_time: float,
        segment_shots: Optional[List[ParsedShot]] = None,
    ) -> str:
        """从完整剧本中提取指定时间段的剧本内容"""
        if segment_shots:
            blocks: List[str] = []
            current_scene_number: Optional[int] = None
            for shot in segment_shots:
                if shot.scene_number != current_scene_number:
                    blocks.append(
                        f"场景 {shot.scene_number}: {shot.scene_title}\n"
                        f"场景档案ID: {shot.scene_profile_id or '未绑定'}\n"
                        f"场景档案版本: {shot.scene_profile_version}\n"
                        f"类型: {shot.scene_type or '未设置'}\n"
                        f"地点: {shot.location or '未设置'}\n"
                        f"时间: {shot.time_label or '未设置'}\n"
                        f"氛围: {shot.atmosphere or '未设置'}"
                    )
                    current_scene_number = shot.scene_number
                blocks.append("\n".join(shot.raw_lines).strip())
            return "\n\n".join(block for block in blocks if block).strip()

        return f"[{start_time:.1f}s - {end_time:.1f}s] " + script[:500]

    def _extract_character_registry(self, script: str) -> Dict[str, str]:
        registry: Dict[str, str] = {}
        in_character_section = False
        current_name = ""

        for raw_line in script.splitlines():
            stripped = raw_line.strip()
            if stripped == "【角色设定】":
                in_character_section = True
                current_name = ""
                continue
            if in_character_section and stripped.startswith("【") and stripped != "【角色设定】":
                break
            if not in_character_section or not stripped:
                continue

            character_match = re.match(r"^(?:角色\s*)?(\d+)[\.\:]\s*(.+)$", stripped)
            if character_match:
                current_name = character_match.group(2).strip()
                continue

            if stripped.startswith("档案ID:") and current_name:
                profile_id = stripped.partition(":")[2].strip()
                if profile_id and profile_id != "未绑定":
                    registry[self._normalize_dialogue_lookup_key(current_name)] = profile_id

        return registry

    def _normalize_dialogue_lookup_key(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).lower()

    def _is_likely_character_id(
        self,
        value: str,
        *,
        character_registry: Dict[str, str],
        segment_character_ids: List[str],
    ) -> bool:
        normalized = str(value or "").strip()
        if not normalized:
            return False
        if normalized in segment_character_ids or normalized in character_registry.values():
            return True
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{5,}", normalized))

    def _resolve_character_id_for_dialogue(
        self,
        *,
        speaker_name: str,
        speaker_character_id: str,
        character_registry: Dict[str, str],
        segment_character_ids: List[str],
    ) -> str:
        normalized_character_id = str(speaker_character_id or "").strip()
        if normalized_character_id:
            return normalized_character_id

        normalized_name = self._normalize_dialogue_lookup_key(speaker_name)
        if normalized_name and normalized_name in character_registry:
            return character_registry[normalized_name]
        if normalized_name and len(segment_character_ids) == 1:
            return segment_character_ids[0]
        return ""

    def _parse_dialogue_text(
        self,
        raw_dialogue: str,
        *,
        character_registry: Dict[str, str],
        segment_character_ids: List[str],
    ) -> SegmentDialogue:
        raw_text = str(raw_dialogue or "").strip()
        if not raw_text:
            return SegmentDialogue(text="")

        speaker_name = ""
        speaker_character_id = ""
        emotion = ""
        tone = ""
        dialogue_text = raw_text

        prefix = ""
        content = ""
        for separator in ("：", ":"):
            if separator in raw_text:
                prefix, content = raw_text.split(separator, 1)
                break

        if prefix:
            bracket_values = re.findall(r"\[([^\]]+)\]", prefix)
            speaker_name = re.sub(r"\[[^\]]+\]", "", prefix).strip()
            dialogue_text = content.strip()

            for item in bracket_values:
                normalized = str(item or "").strip()
                if not normalized:
                    continue
                if (
                    not speaker_character_id
                    and self._is_likely_character_id(
                        normalized,
                        character_registry=character_registry,
                        segment_character_ids=segment_character_ids,
                    )
                ):
                    speaker_character_id = normalized
                    continue

                labels = [part.strip() for part in re.split(r"\s*/\s*", normalized) if part.strip()]
                if labels and not emotion:
                    emotion = labels[0]
                if len(labels) >= 2 and not tone:
                    tone = labels[1]

        speaker_character_id = self._resolve_character_id_for_dialogue(
            speaker_name=speaker_name,
            speaker_character_id=speaker_character_id,
            character_registry=character_registry,
            segment_character_ids=segment_character_ids,
        )

        return SegmentDialogue(
            text=dialogue_text or raw_text,
            speaker_name=speaker_name,
            speaker_character_id=speaker_character_id,
            emotion=emotion,
            tone=tone,
        )

    def _normalize_segment_dialogues(
        self,
        raw_dialogues: Any,
        *,
        character_registry: Dict[str, str],
        segment_character_ids: List[str],
        limit: int = 4,
    ) -> List[SegmentDialogue]:
        if isinstance(raw_dialogues, (str, dict, SegmentDialogue)):
            iterable = [raw_dialogues]
        elif isinstance(raw_dialogues, (list, tuple)):
            iterable = list(raw_dialogues)
        else:
            iterable = []

        normalized_items: List[SegmentDialogue] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        for raw_item in iterable:
            dialogue: Optional[SegmentDialogue]
            if isinstance(raw_item, SegmentDialogue):
                dialogue = SegmentDialogue(
                    text=str(raw_item.text or "").strip(),
                    speaker_name=str(raw_item.speaker_name or "").strip(),
                    speaker_character_id=str(raw_item.speaker_character_id or "").strip(),
                    emotion=str(raw_item.emotion or "").strip(),
                    tone=str(raw_item.tone or "").strip(),
                )
            elif isinstance(raw_item, dict):
                speaker_name = str(raw_item.get("speaker_name") or raw_item.get("speaker") or "").strip()
                speaker_character_id = str(raw_item.get("speaker_character_id") or raw_item.get("character_id") or "").strip()
                dialogue = SegmentDialogue(
                    text=str(raw_item.get("text") or raw_item.get("dialogue") or "").strip(),
                    speaker_name=speaker_name,
                    speaker_character_id=self._resolve_character_id_for_dialogue(
                        speaker_name=speaker_name,
                        speaker_character_id=speaker_character_id,
                        character_registry=character_registry,
                        segment_character_ids=segment_character_ids,
                    ),
                    emotion=str(raw_item.get("emotion") or "").strip(),
                    tone=str(raw_item.get("tone") or "").strip(),
                )
            else:
                dialogue = self._parse_dialogue_text(
                    str(raw_item),
                    character_registry=character_registry,
                    segment_character_ids=segment_character_ids,
                )

            if not str((dialogue.text if dialogue else "") or "").strip():
                continue

            fingerprint = (
                str(dialogue.text or "").strip(),
                str(dialogue.speaker_name or "").strip(),
                str(dialogue.speaker_character_id or "").strip(),
                str(dialogue.emotion or "").strip(),
                str(dialogue.tone or "").strip(),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            normalized_items.append(dialogue)
            if len(normalized_items) >= limit:
                break

        return normalized_items

    def _dialogue_display_text(
        self,
        dialogue: SegmentDialogue,
        *,
        include_character_id: bool = True,
    ) -> str:
        text = str(dialogue.text or "").strip()
        speaker_name = str(dialogue.speaker_name or "").strip()
        speaker_character_id = str(dialogue.speaker_character_id or "").strip()
        label_items = [part for part in [str(dialogue.emotion or "").strip(), str(dialogue.tone or "").strip()] if part]

        prefix = speaker_name
        if include_character_id and speaker_character_id:
            prefix = f"{prefix} [{speaker_character_id}]".strip()
        if label_items:
            prefix = f"{prefix} [{' / '.join(label_items)}]".strip()

        if prefix and text:
            return f"{prefix}: {text}"
        return text or prefix

    def _serialize_segment_dialogues(self, dialogues: List[SegmentDialogue]) -> List[Dict[str, str]]:
        return [
            {
                "text": str(dialogue.text or "").strip(),
                "speaker_name": str(dialogue.speaker_name or "").strip(),
                "speaker_character_id": str(dialogue.speaker_character_id or "").strip(),
                "emotion": str(dialogue.emotion or "").strip(),
                "tone": str(dialogue.tone or "").strip(),
            }
            for dialogue in dialogues
            if str(dialogue.text or "").strip()
        ]
    
    async def _generate_video_prompt(
        self, 
        segment_script: str, 
        point: Dict,
        segment_shots: List[ParsedShot],
        has_previous: bool,
        has_next: bool
    ) -> Dict:
        """为片段生成视频生成Prompt"""
        llm_prompt = await self._generate_video_prompt_with_llm(
            segment_script=segment_script,
            point=point,
            segment_shots=segment_shots,
            has_previous=has_previous,
            has_next=has_next,
        )
        if llm_prompt:
            return llm_prompt

        return self._build_local_video_prompt(
            segment_script=segment_script,
            point=point,
            segment_shots=segment_shots,
            has_previous=has_previous,
            has_next=has_next,
        )
    
    def _generate_continuity_points(self, segments: List[VideoSegment]) -> List[Dict]:
        """生成片段间的衔接点信息"""
        
        continuity_points = []
        
        for i in range(len(segments) - 1):
            current = segments[i]
            next_seg = segments[i + 1]
            
            point = {
                "between_segments": [current.segment_number, next_seg.segment_number],
                "recommended_transition": "cut" if i % 2 == 0 else "dissolve",
                "continuity_notes": f"片段{current.segment_number}结尾过渡到片段{next_seg.segment_number}开头",
                "audio_bridge_suggestion": "保持环境音连续性"
            }
            
            continuity_points.append(point)
        
        return continuity_points

    def _parse_structured_script(self, script: str) -> List[ParsedShot]:
        """解析由完整剧本阶段输出的文本，提取场景与镜头时间线。"""
        lines = script.splitlines()
        scene_pattern = re.compile(r"^场景\s+(\d+):\s*(.+)$")
        shot_pattern = re.compile(r"^镜头\s+(\d+)\s*\|\s*时长\s*([\d.]+)\s*秒$")

        current_scene = {
            "scene_number": 0,
            "scene_title": "",
            "scene_type": "",
            "scene_profile_id": "",
            "scene_profile_version": 1,
            "location": "",
            "time_label": "",
            "atmosphere": "",
        }
        current_shot: Optional[ParsedShot] = None
        current_section: Optional[str] = None
        parsed_shots: List[ParsedShot] = []

        def flush_shot() -> None:
            nonlocal current_shot
            if current_shot:
                current_shot.raw_lines = [line for line in current_shot.raw_lines if line.strip()]
                parsed_shots.append(current_shot)
                current_shot = None

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            scene_match = scene_pattern.match(stripped)
            if scene_match:
                flush_shot()
                current_scene = {
                    "scene_number": int(scene_match.group(1)),
                    "scene_title": scene_match.group(2).strip(),
                    "scene_type": "",
                    "scene_profile_id": "",
                    "scene_profile_version": 1,
                    "location": "",
                    "time_label": "",
                    "atmosphere": "",
                }
                current_section = None
                continue

            shot_match = shot_pattern.match(stripped)
            if shot_match:
                flush_shot()
                current_shot = ParsedShot(
                    scene_number=current_scene["scene_number"],
                    scene_title=current_scene["scene_title"],
                    scene_type=current_scene["scene_type"],
                    scene_profile_id=current_scene["scene_profile_id"],
                    scene_profile_version=current_scene["scene_profile_version"],
                    location=current_scene["location"],
                    time_label=current_scene["time_label"],
                    atmosphere=current_scene["atmosphere"],
                    shot_number=int(shot_match.group(1)),
                    duration=float(shot_match.group(2)),
                    raw_lines=[stripped],
                )
                current_section = None
                continue

            if current_shot is None:
                if stripped.startswith("类型:"):
                    current_scene["scene_type"] = stripped.partition(":")[2].strip()
                elif stripped.startswith("场景档案ID:"):
                    current_scene["scene_profile_id"] = stripped.partition(":")[2].strip()
                elif stripped.startswith("场景档案版本:"):
                    current_scene["scene_profile_version"] = self._safe_int(stripped.partition(":")[2].strip(), default=1)
                elif stripped.startswith("地点:"):
                    current_scene["location"] = stripped.partition(":")[2].strip()
                elif stripped.startswith("时间:"):
                    current_scene["time_label"] = stripped.partition(":")[2].strip()
                elif stripped.startswith("氛围:"):
                    current_scene["atmosphere"] = stripped.partition(":")[2].strip()
                continue

            current_shot.raw_lines.append(stripped)
            if stripped.startswith("景别:"):
                current_shot.shot_type = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("场景档案绑定:"):
                binding_text = stripped.partition(":")[2].strip()
                profile_id, _, version_text = binding_text.partition("|")
                current_shot.scene_profile_id = profile_id.strip()
                current_shot.scene_profile_version = self._safe_int(version_text.replace("版本", "").strip(), default=current_scene["scene_profile_version"])
                current_section = None
            elif stripped.startswith("角色档案绑定:"):
                value = stripped.partition(":")[2].strip()
                current_shot.character_profile_ids = [] if value in {"", "无"} else [item.strip() for item in value.split(",") if item.strip()]
                current_section = None
            elif stripped.startswith("镜头重点:"):
                current_shot.prompt_focus = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("机位角度:"):
                current_shot.camera_angle = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("运动方式:"):
                current_shot.camera_movement = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("画面描述:"):
                current_shot.description = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("环境细节:"):
                current_shot.environment = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("光线:"):
                current_shot.lighting = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("出镜角色:"):
                value = stripped.partition(":")[2].strip()
                current_shot.characters_in_shot = [] if value in {"", "无"} else [item.strip() for item in value.split(",") if item.strip()]
                current_section = None
            elif stripped.startswith("动作:"):
                current_section = "actions"
            elif stripped.startswith("对话:"):
                current_section = "dialogues"
            elif stripped.startswith("音效:"):
                value = stripped.partition(":")[2].strip()
                current_shot.sound_effects = [item.strip() for item in value.split(",") if item.strip()]
                current_section = None
            elif stripped.startswith("音乐:"):
                current_shot.music = stripped.partition(":")[2].strip()
                current_section = None
            elif stripped.startswith("-"):
                value = stripped[1:].strip()
                if current_section == "actions":
                    current_shot.actions.append(value)
                elif current_section == "dialogues":
                    current_shot.dialogues.append(value)

        flush_shot()

        cursor = 0.0
        for shot in parsed_shots:
            shot.start_time = round(cursor, 2)
            cursor += shot.duration
            shot.end_time = round(cursor, 2)

        return parsed_shots

    def _build_shots_summary(self, segment_shots: List[ParsedShot]) -> str:
        if not segment_shots:
            return ""
        summary_parts = []
        for shot in segment_shots:
            bit = f"镜头{shot.shot_number}"
            if shot.description:
                bit += f"：{shot.description}"
            if shot.prompt_focus:
                bit += f"；重点 {shot.prompt_focus}"
            if shot.camera_movement:
                bit += f"；镜头运动 {shot.camera_movement}"
            summary_parts.append(bit)
        return "\n".join(summary_parts)

    def _build_segment_prompt_focus(self, segment_shots: List[ParsedShot]) -> str:
        focuses = self._collect_unique_items([shot.prompt_focus for shot in segment_shots if shot.prompt_focus], limit=3)
        if focuses:
            return "；".join(focuses)
        descriptions = self._collect_unique_items([shot.description for shot in segment_shots if shot.description], limit=2)
        return "；".join(descriptions)

    def _identify_primary_character_ids(self, parsed_shots: List[ParsedShot]) -> List[str]:
        if not parsed_shots:
            return []

        stats: Dict[str, Dict[str, float]] = {}
        total_duration = max(float(parsed_shots[-1].end_time or 0.0), 1.0)
        for shot in parsed_shots:
            unique_ids = self._collect_unique_items(
                [profile_id for profile_id in shot.character_profile_ids if profile_id],
                limit=20,
            )
            for profile_id in unique_ids:
                entry = stats.setdefault(profile_id, {"duration": 0.0, "shots": 0.0})
                entry["duration"] += float(shot.duration or 0.0)
                entry["shots"] += 1.0

        if not stats:
            return []

        ranked = sorted(
            stats.items(),
            key=lambda item: (-item[1]["duration"], -item[1]["shots"], item[0]),
        )
        duration_threshold = max(3.0, total_duration * 0.18)
        selected = [
            profile_id
            for profile_id, meta in ranked
            if meta["duration"] >= duration_threshold or meta["shots"] >= 2
        ][:2]
        if not selected:
            selected = [ranked[0][0]]
        return selected

    def _shots_contain_primary_characters(
        self,
        segment_shots: List[ParsedShot],
        primary_character_ids: List[str],
    ) -> bool:
        if not segment_shots or not primary_character_ids:
            return False
        primary_set = set(primary_character_ids)
        return any(primary_set.intersection(set(shot.character_profile_ids or [])) for shot in segment_shots)

    def _ending_shot_contains_primary_characters(
        self,
        segment_shots: List[ParsedShot],
        primary_character_ids: List[str],
    ) -> bool:
        if not segment_shots or not primary_character_ids:
            return False
        return bool(set(primary_character_ids).intersection(set(segment_shots[-1].character_profile_ids or [])))

    def _collect_segment_character_ids(self, segment_shots: List[ParsedShot]) -> List[str]:
        return self._collect_unique_items(
            [profile_id for shot in segment_shots for profile_id in shot.character_profile_ids if profile_id],
            limit=20,
        )

    def _first_shot_character_ids(self, segment_shots: List[ParsedShot]) -> List[str]:
        if not segment_shots:
            return []
        return self._collect_unique_items(
            [profile_id for profile_id in (segment_shots[0].character_profile_ids or []) if profile_id],
            limit=20,
        )

    def _ending_shot_contains_character_ids(
        self,
        segment_shots: List[ParsedShot],
        character_ids: List[str],
    ) -> bool:
        if not segment_shots or not character_ids:
            return False
        return bool(set(character_ids).intersection(set(segment_shots[-1].character_profile_ids or [])))

    def _collect_late_entry_character_ids(self, segment_shots: List[ParsedShot]) -> List[str]:
        if len(segment_shots) <= 1:
            return []

        first_shot_character_ids = set(self._first_shot_character_ids(segment_shots))
        late_entry_character_ids: List[str] = []
        for shot in segment_shots[1:]:
            for profile_id in shot.character_profile_ids or []:
                normalized = str(profile_id or "").strip()
                if not normalized or normalized in first_shot_character_ids or normalized in late_entry_character_ids:
                    continue
                late_entry_character_ids.append(normalized)
        return late_entry_character_ids

    def _rebuild_split_points_from_boundaries(
        self,
        *,
        boundaries: List[float],
        parsed_shots: List[ParsedShot],
        target_duration: float,
        split_reason: str,
        enforce_duration_limits: bool = True,
    ) -> List[Dict[str, Any]]:
        if not boundaries or not parsed_shots:
            return []

        min_duration = float(self.config.min_segment_duration)
        max_duration = float(self.config.max_segment_duration)
        total_duration = round(min(float(target_duration), float(parsed_shots[-1].end_time)), 2)
        normalized_boundaries = sorted(
            {
                round(point, 2)
                for point in boundaries
                if min_duration - 0.01 <= round(point, 2) <= total_duration + 0.01
            }
        )
        if not normalized_boundaries or abs(normalized_boundaries[-1] - total_duration) > 0.01:
            return []

        rebuilt: List[Dict[str, Any]] = []
        start_time = 0.0
        for index, end_time in enumerate(normalized_boundaries, start=1):
            duration = round(end_time - start_time, 2)
            if duration < min_duration - 0.01:
                return []
            if enforce_duration_limits and duration > max_duration + 0.01:
                return []
            segment_shots = self._slice_shots_by_time(parsed_shots, start_time, end_time)
            if not segment_shots:
                return []
            rebuilt.append(
                {
                    "segment_number": index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "split_reason": split_reason,
                    "title": "",
                    "description": "",
                    "key_actions": [],
                    "key_dialogues": [],
                    "continuity_from_prev": "",
                    "continuity_to_next": "",
                    "prompt_focus": "",
                    "shots": segment_shots,
                }
            )
            start_time = end_time

        return rebuilt

    def _optimize_split_points_for_character_continuity(
        self,
        *,
        split_points: List[Dict[str, Any]],
        parsed_shots: List[ParsedShot],
        target_duration: float,
    ) -> List[Dict[str, Any]]:
        if not split_points or not parsed_shots:
            return split_points

        min_duration = float(self.config.min_segment_duration)
        existing_boundaries = sorted({round(float(point.get("end_time") or 0.0), 2) for point in split_points})
        seen_character_ids: set[str] = set()
        candidate_boundaries: List[tuple[float, List[str]]] = []

        for shot in parsed_shots:
            shot_character_ids = self._collect_unique_items(
                [profile_id for profile_id in shot.character_profile_ids if profile_id],
                limit=20,
            )
            new_character_ids = [profile_id for profile_id in shot_character_ids if profile_id not in seen_character_ids]
            if new_character_ids and float(shot.start_time) > 0.01:
                candidate_boundaries.append((round(float(shot.start_time), 2), new_character_ids))
            seen_character_ids.update(shot_character_ids)

        if not candidate_boundaries:
            return split_points

        updated_boundaries = list(existing_boundaries)
        changed = False
        for boundary_time, new_character_ids in candidate_boundaries:
            if boundary_time in updated_boundaries:
                continue
            previous_boundary = max((point for point in updated_boundaries if point < boundary_time), default=0.0)
            next_boundary = min(
                (point for point in updated_boundaries if point > boundary_time),
                default=round(min(float(target_duration), float(parsed_shots[-1].end_time)), 2),
            )
            if boundary_time - previous_boundary < min_duration - 0.01:
                continue
            if next_boundary - boundary_time < min_duration - 0.01:
                continue
            updated_boundaries.append(boundary_time)
            updated_boundaries.sort()
            changed = True
            logger.info(
                "Added split at %.2fs for new character entry: %s",
                boundary_time,
                ", ".join(new_character_ids),
            )

        if not changed:
            return split_points

        rebuilt = self._rebuild_split_points_from_boundaries(
            boundaries=updated_boundaries,
            parsed_shots=parsed_shots,
            target_duration=target_duration,
            split_reason="new_character_entry_split",
            enforce_duration_limits=False,
        )
        return rebuilt or split_points

    def _optimize_split_points_for_first_frame_character_stability(
        self,
        *,
        split_points: List[Dict[str, Any]],
        parsed_shots: List[ParsedShot],
        target_duration: float,
    ) -> List[Dict[str, Any]]:
        if not split_points or not parsed_shots:
            return split_points

        min_duration = float(self.config.min_segment_duration)
        boundaries = sorted({round(float(point.get("end_time") or 0.0), 2) for point in split_points})
        changed = False

        for _ in range(max(len(parsed_shots), 1)):
            rebuilt = self._rebuild_split_points_from_boundaries(
                boundaries=boundaries,
                parsed_shots=parsed_shots,
                target_duration=target_duration,
                split_reason="character_first_frame_stability_split",
                enforce_duration_limits=False,
            )
            if not rebuilt:
                break

            added_boundary = False
            for point in rebuilt:
                segment_shots: List[ParsedShot] = point.get("shots", []) or []
                if len(segment_shots) <= 1:
                    continue

                segment_start = round(float(point.get("start_time") or 0.0), 2)
                segment_end = round(float(point.get("end_time") or 0.0), 2)
                first_shot_character_ids = set(self._first_shot_character_ids(segment_shots))

                for shot in segment_shots[1:]:
                    shot_start_time = round(float(shot.start_time), 2)
                    shot_character_ids = {
                        str(profile_id or "").strip()
                        for profile_id in (shot.character_profile_ids or [])
                        if str(profile_id or "").strip()
                    }
                    introduced_character_ids = sorted(shot_character_ids - first_shot_character_ids)
                    if not introduced_character_ids or shot_start_time in boundaries:
                        continue
                    if shot_start_time - segment_start < min_duration - 0.01:
                        continue
                    if segment_end - shot_start_time < min_duration - 0.01:
                        continue

                    boundaries.append(shot_start_time)
                    boundaries.sort()
                    changed = True
                    added_boundary = True
                    logger.info(
                        "Added split at %.2fs to keep first-frame characters stable. Later-entering characters: %s",
                        shot_start_time,
                        ", ".join(introduced_character_ids),
                    )
                    break

                if added_boundary:
                    break

            if not added_boundary:
                break

        if not changed:
            return split_points

        rebuilt = self._rebuild_split_points_from_boundaries(
            boundaries=boundaries,
            parsed_shots=parsed_shots,
            target_duration=target_duration,
            split_reason="character_first_frame_stability_split",
            enforce_duration_limits=False,
        )
        return rebuilt or split_points

    def _annotate_segments_for_video_generation(
        self,
        *,
        segments: List[VideoSegment],
        parsed_shots: List[ParsedShot],
    ) -> List[VideoSegment]:
        if not segments:
            return segments

        primary_character_ids = self._identify_primary_character_ids(parsed_shots)
        segment_character_ids: List[List[str]] = []
        segment_ending_character_ids: List[List[str]] = []
        seen_character_ids: set[str] = set()

        for index, segment in enumerate(segments):
            segment_shots = self._slice_shots_by_time(
                parsed_shots,
                float(segment.start_time),
                float(segment.end_time),
            )
            character_ids = self._collect_segment_character_ids(segment_shots)
            first_shot_character_ids = self._first_shot_character_ids(segment_shots)
            late_entry_character_ids = self._collect_late_entry_character_ids(segment_shots)
            new_character_ids = [profile_id for profile_id in character_ids if profile_id not in seen_character_ids]
            contains_primary = self._shots_contain_primary_characters(segment_shots, primary_character_ids)
            ending_contains_primary = self._ending_shot_contains_primary_characters(segment_shots, primary_character_ids)

            segment.contains_primary_character = contains_primary
            segment.ending_contains_primary_character = ending_contains_primary
            segment.new_character_profile_ids = new_character_ids
            segment.late_entry_character_profile_ids = late_entry_character_ids
            segment.pre_generate_start_frame = index == 0
            segment.start_frame_generation_reason = "opening_segment" if index == 0 else ""
            segment.prefer_primary_character_end_frame = index < len(segments) - 1 and contains_primary
            if index > 0 and set(new_character_ids).intersection(set(first_shot_character_ids)):
                segment.pre_generate_start_frame = True
                segment.start_frame_generation_reason = "new_character_entry"

            seen_character_ids.update(character_ids)
            segment_character_ids.append(character_ids)
            segment_ending_character_ids.append(
                self._collect_unique_items(
                    [profile_id for profile_id in (segment_shots[-1].character_profile_ids if segment_shots else []) if profile_id],
                    limit=20,
                )
            )

        for index, segment in enumerate(segments[:-1]):
            next_character_ids = segment_character_ids[index + 1]
            handoff_character_ids = [profile_id for profile_id in segment_character_ids[index] if profile_id in next_character_ids]
            segment.handoff_character_profile_ids = handoff_character_ids
            segment.prefer_character_handoff_end_frame = bool(handoff_character_ids)
            segment.ending_contains_handoff_characters = bool(
                set(handoff_character_ids).intersection(set(segment_ending_character_ids[index]))
            )
            if segment.prefer_character_handoff_end_frame:
                segment.prefer_primary_character_end_frame = True

        return segments

    def _merge_profile_versions(self, segment_shots: List[ParsedShot]) -> Dict[str, int]:
        merged: Dict[str, int] = {}
        for shot in segment_shots:
            for profile_id, version in (shot.character_profile_versions or {}).items():
                if profile_id and profile_id not in merged:
                    merged[profile_id] = int(version or 1)
            for profile_id in shot.character_profile_ids:
                merged.setdefault(profile_id, 1)
        return merged

    def _build_segment_title(self, point: Dict[str, Any], segment_shots: List[ParsedShot]) -> str:
        if not segment_shots:
            return f"片段{point['segment_number']}"
        first = segment_shots[0]
        last = segment_shots[-1]
        if first.scene_number == last.scene_number:
            return f"场景{first.scene_number} · {first.scene_title}"
        return f"场景{first.scene_number}-{last.scene_number}衔接段"

    def _truncate_text(self, text: str, limit: int) -> str:
        normalized = str(text or "").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    def _build_segment_opening_clause(self, segment_shots: List[ParsedShot]) -> str:
        if not segment_shots:
            return ""
        first = segment_shots[0]
        opening_parts = self._collect_unique_items(
            [
                first.description,
                first.environment,
                first.prompt_focus,
                "、".join(first.characters_in_shot[:3]) if first.characters_in_shot else "",
            ],
            limit=4,
        )
        return "，".join(item for item in opening_parts if item)

    def _build_segment_action_progression(self, segment_shots: List[ParsedShot]) -> str:
        if not segment_shots:
            return ""
        first = segment_shots[0]
        last = segment_shots[-1]
        middle_shots = segment_shots[1:-1]

        start_bit = self._collect_unique_items([first.description, *first.actions], limit=2)
        middle_bits = self._collect_unique_items(
            [item for shot in middle_shots for item in [shot.description, *shot.actions] if item],
            limit=2,
        )
        end_bit = self._collect_unique_items([last.description, *last.actions], limit=2)

        clauses: List[str] = []
        if start_bit:
            clauses.append(f"开场 {start_bit[0]}")
        for index, item in enumerate(middle_bits):
            clauses.append(("随后 " if index == 0 else "接着 ") + item)
        if end_bit:
            ending = end_bit[0]
            if not clauses or ending not in clauses[-1]:
                clauses.append(f"结尾停在 {ending}")
        return "；".join(clauses)

    def _build_segment_camera_clause(self, segment_shots: List[ParsedShot]) -> str:
        shot_types = self._collect_unique_items([shot.shot_type for shot in segment_shots if shot.shot_type], limit=3)
        angles = self._collect_unique_items([shot.camera_angle for shot in segment_shots if shot.camera_angle], limit=2)
        movements = self._collect_unique_items([shot.camera_movement for shot in segment_shots if shot.camera_movement], limit=3)
        parts: List[str] = []
        if shot_types:
            parts.append(f"景别 {', '.join(shot_types)}")
        if angles:
            parts.append(f"角度 {', '.join(angles)}")
        if movements:
            parts.append(f"运镜 {', '.join(movements)}")
        return "；".join(parts)

    def _build_segment_dialogue_clause(self, segment_shots: List[ParsedShot]) -> str:
        dialogue_lines = self._collect_unique_items(
            [self._truncate_text(dialogue, 36) for shot in segment_shots for dialogue in shot.dialogues if dialogue],
            limit=2,
        )
        if not dialogue_lines:
            return ""
        return "；".join(dialogue_lines)

    def _build_segment_ending_clause(self, segment_shots: List[ParsedShot]) -> str:
        if not segment_shots:
            return ""
        last = segment_shots[-1]
        ending_parts = self._collect_unique_items(
            [
                last.description,
                last.prompt_focus,
                last.environment,
                "、".join(last.characters_in_shot[:3]) if last.characters_in_shot else "",
            ],
            limit=4,
        )
        return "，".join(item for item in ending_parts if item)

    def _build_local_video_prompt(
        self,
        *,
        segment_script: str,
        point: Dict[str, Any],
        segment_shots: List[ParsedShot],
        has_previous: bool,
        has_next: bool,
    ) -> Dict[str, Any]:
        first = segment_shots[0] if segment_shots else None
        locations = self._collect_unique_items([shot.location for shot in segment_shots if shot.location], limit=2)
        characters = self._collect_unique_items(
            [character for shot in segment_shots for character in shot.characters_in_shot if character and character != "无"],
            limit=6,
        )
        shot_descriptions = self._collect_unique_items([shot.description for shot in segment_shots if shot.description], limit=5)
        movements = self._collect_unique_items([shot.camera_movement for shot in segment_shots if shot.camera_movement], limit=3)
        actions = self._collect_unique_items([action for shot in segment_shots for action in shot.actions], limit=6)
        dialogues = self._collect_unique_items([dialogue for shot in segment_shots for dialogue in shot.dialogues], limit=3)
        lighting = self._collect_unique_items([shot.lighting for shot in segment_shots if shot.lighting], limit=2)
        atmosphere = self._collect_unique_items([shot.atmosphere for shot in segment_shots if shot.atmosphere], limit=2)
        prompt_focus = str(point.get("prompt_focus") or self._build_segment_prompt_focus(segment_shots) or "")
        opening_clause = self._build_segment_opening_clause(segment_shots)
        action_progression = self._build_segment_action_progression(segment_shots)
        camera_clause = self._build_segment_camera_clause(segment_shots)
        dialogue_clause = self._build_segment_dialogue_clause(segment_shots)
        ending_clause = self._build_segment_ending_clause(segment_shots)

        prompt_sentences = [
            "电影感写实短视频，单段连续生成，不要做成信息罗列式分镜清单。",
            f"时长约 {float(point['duration']):.1f} 秒。",
            (
                "场景设定："
                + "，".join(
                    item
                    for item in [
                        first.scene_title if first and first.scene_title else "",
                        " / ".join(locations) if locations else "",
                        " / ".join(lighting) if lighting else "",
                        " / ".join(atmosphere) if atmosphere else "",
                    ]
                    if item
                )
                + "。"
            )
            if first and any([first.scene_title, locations, lighting, atmosphere])
            else "",
            f"出场主体：{'、'.join(characters)}。" if characters else "",
            f"首帧画面：{opening_clause}。" if opening_clause else "",
            f"动作推进：{action_progression}。" if action_progression else "",
            f"镜头设计：{camera_clause}。" if camera_clause else "",
            f"视觉重点：{prompt_focus}。" if prompt_focus else "",
            f"对白或口型重点：{dialogue_clause}。" if dialogue_clause else "",
            "保持角色身份、服装、体态、空间朝向和动作连贯，避免跳切、重复动作和主体漂移。",
        ]
        if shot_descriptions:
            prompt_sentences.append(f"关键画面参考：{'；'.join(shot_descriptions[:3])}。")
        if actions and not action_progression:
            prompt_sentences.append(f"关键动作：{'；'.join(actions[:3])}。")
        if dialogues and not dialogue_clause:
            prompt_sentences.append(f"对白重点：{'；'.join(dialogues[:2])}。")
        if has_previous:
            prompt_sentences.append("开头要自然承接上一段的动作和情绪，不要重新起势或突然换位。")
        if has_next:
            prompt_sentences.append("结尾要留出清晰可延续的动作、视线或人物在位状态，方便下一段无缝接续。")
        if point.get("prefer_character_handoff_end_frame"):
            prompt_sentences.append("结尾保持下一段仍会继续出现的角色清楚留在画面内，作为交接尾帧。")
        elif point.get("prefer_primary_character_end_frame"):
            prompt_sentences.append("结尾保持主角色清楚留在画面内，作为下一段承接尾帧。")
        if ending_clause:
            prompt_sentences.append(f"结尾画面：{ending_clause}。")

        prompt = " ".join(sentence for sentence in prompt_sentences if sentence)

        return {
            "prompt": prompt,
            "negative_prompt": (
                "卡通化, 二次元, 信息图排版, 分屏, 多宫格, 字幕烧录, 水印, 低清晰度, 模糊, 解剖错误, "
                "角色漂移, 服装突变, 跳切, 重复动作循环, 镜头逻辑断裂, 空间关系错误"
            ),
            "config": {
                "duration": min(point["duration"], self.config.max_segment_duration),
                "aspect_ratio": "16:9",
                "style": "cinematic_realistic",
                "source": "structured-script-splitter",
            },
            "segment_script": segment_script,
        }

    def _describe_transition_in(self, previous_shots: List[ParsedShot], current_shots: List[ParsedShot]) -> str:
        if not previous_shots or not current_shots:
            return ""
        prev = previous_shots[-1]
        curr = current_shots[0]
        return f"承接上段镜头{prev.shot_number}的动作/视线，切入镜头{curr.shot_number}，保持角色位置与情绪连续"

    def _describe_transition_out(self, current_shots: List[ParsedShot], next_shots: List[ParsedShot]) -> str:
        if not current_shots or not next_shots:
            return ""
        curr = current_shots[-1]
        nxt = next_shots[0]
        return f"以镜头{curr.shot_number}结尾动作或视线为引子，过渡到下一段镜头{nxt.shot_number}"

    def _collect_unique_items(self, items: List[str], limit: int) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
            if len(result) >= limit:
                break
        return result

    def _safe_int(self, value: Any, *, default: int) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            normalized = int(default)
        return normalized if normalized > 0 else int(default)

    async def _plan_segments_with_llm(
        self,
        *,
        script: str,
        analysis: Dict[str, Any],
        target_duration: float,
    ) -> List[Dict[str, Any]]:
        parsed_shots: List[ParsedShot] = analysis.get("parsed_shots", []) or []
        if not parsed_shots:
            return []

        candidate_boundaries = self._build_candidate_boundaries(parsed_shots, target_duration)
        timeline = self._build_shot_timeline_for_llm(parsed_shots, target_duration)

        system_prompt = f"""你是一位专业的视频分段导演。你的任务是把完整剧本拆成多个高质量视频片段，用于逐段生成视频。

拆分规则：
1. 每个片段时长尽量控制在 {self.config.min_segment_duration:.0f}-{self.config.max_segment_duration:.0f} 秒，并且优先靠近 {self.config.max_segment_duration:.0f} 秒
2. 优先保证剧情节奏和镜头连续性，而不是机械平均切分
3. 尽量不要截断一句完整对话、一个完整动作或同一镜头组内部的情绪推进
4. 每个片段内部的镜头必须形成一个“单次视频模型可理解、可直接生成”的完整小节奏
5. 必须只使用候选边界中的时间点作为片段起止时间
6. 输出每个片段的优化信息：标题、片段描述、关键动作、关键对话、与前后片段衔接说明、该片段视频生成 prompt_focus
7. 除最后一个片段外，不要把片段平均切短。像 6 秒 + 7 秒 这种拆法不理想，应优先改成接近 10 秒 + 剩余片段时长
8. 如果总时长有余量，优先让前面的片段更接近 10 秒，最后一个片段再承担剩余的 3-9 秒
9. 任何新角色首次正式登场时，优先从该角色出镜镜头开始新起一段，让该段首帧可以清楚承载角色造型
10. 除最后一个片段外，若下一段继续使用同一批角色，尽量让本段结尾仍保留这些角色在画面内，方便下一段延续角色一致性
11. 尽量不要让首镜头里没有出现的角色在同一段中途入场；如果某角色会在段内首次出镜，优先从该角色出镜镜头开始新起一段
12. 片段 description 和 prompt_focus 必须面向视频模型理解：写清楚首帧主体、动作推进、镜头运动、空间关系、结尾停点，不要写成抽象剧情总结

输出必须是合法 JSON，格式：
{{
  "segments": [
    {{
      "segment_number": 1,
      "start_time": 0.0,
      "end_time": 10.0,
      "title": "片段标题",
      "description": "片段描述",
      "key_actions": ["动作1", "动作2"],
      "key_dialogues": ["对话1"],
      "continuity_from_prev": "",
      "continuity_to_next": "如何衔接下一段",
      "prompt_focus": "这一段视频生成最重要的视觉/动作/镜头重点",
      "split_reason": "为什么在这里切"
    }}
  ]
}}

不要输出解释文字，不要输出 markdown 代码块。"""

        user_prompt = (
            f"完整剧本如下：\n{script[:6000]}\n\n"
            f"镜头时间线如下：\n{timeline}\n\n"
            f"可选边界时间点（必须从这些时间点中选择起止时间）:\n{json.dumps(candidate_boundaries, ensure_ascii=False)}\n\n"
            f"目标总时长：{target_duration:.1f} 秒。请直接输出 JSON。"
        )

        try:
            messages = [
                DoubaoMessage(role="system", content=system_prompt),
                DoubaoMessage(role="user", content=user_prompt),
            ]
            response = await self.llm.chat_completion(
                messages,
                temperature=0.35,
                max_tokens=2600,
            )
            payload = self._parse_llm_json(response.get_content().strip())
            raw_segments = payload.get("segments") or []
            return self._validate_llm_segments(
                raw_segments=raw_segments,
                parsed_shots=parsed_shots,
                target_duration=target_duration,
                candidate_boundaries=candidate_boundaries,
                enforce_duration_limits=False,
            )
        except Exception as exc:
            logger.warning("LLM segment planning failed: %s", exc)
            return []

    def _build_candidate_boundaries(
        self,
        parsed_shots: List[ParsedShot],
        target_duration: float,
    ) -> List[float]:
        boundaries = [0.0]
        accumulated = 0.0
        for index, shot in enumerate(parsed_shots):
            if shot.end_time > target_duration + 0.01:
                break
            scene_boundary = index > 0 and shot.scene_number != parsed_shots[index - 1].scene_number
            if (
                shot.end_time not in boundaries
                and (
                    scene_boundary
                    or shot.end_time - boundaries[-1] >= self.config.min_segment_duration
                    or shot.duration >= self.config.max_segment_duration
                )
            ):
                boundaries.append(round(shot.end_time, 2))
            accumulated = shot.end_time

        if accumulated and round(accumulated, 2) not in boundaries:
            boundaries.append(round(accumulated, 2))

        boundaries = sorted({round(point, 2) for point in boundaries if 0.0 <= point <= target_duration + 0.01})
        return boundaries

    def _build_shot_timeline_for_llm(self, parsed_shots: List[ParsedShot], target_duration: float) -> str:
        lines: List[str] = []
        for shot in parsed_shots:
            if shot.start_time >= target_duration + 0.01:
                break
            actions = "；".join(shot.actions[:2]) if shot.actions else "无"
            dialogues = "；".join(shot.dialogues[:2]) if shot.dialogues else "无"
            characters = "、".join(shot.characters_in_shot[:3]) if shot.characters_in_shot else "无"
            character_ids = "、".join(shot.character_profile_ids[:3]) if shot.character_profile_ids else "无"
            lines.append(
                f"{shot.start_time:.1f}-{shot.end_time:.1f}s | 场景{shot.scene_number} {shot.scene_title} | "
                f"镜头{shot.shot_number} | 人物:{characters} | 角色档案:{character_ids} | "
                f"{shot.description or '无描述'} | 动作:{actions} | 对话:{dialogues}"
            )
        return "\n".join(lines)

    def _validate_llm_segments(
        self,
        *,
        raw_segments: List[Dict[str, Any]],
        parsed_shots: List[ParsedShot],
        target_duration: float,
        candidate_boundaries: List[float],
        enforce_duration_limits: bool = True,
    ) -> List[Dict[str, Any]]:
        if not raw_segments:
            return []

        valid_boundaries = {round(point, 2) for point in candidate_boundaries}
        results: List[Dict[str, Any]] = []
        previous_end = 0.0

        for index, raw in enumerate(raw_segments, start=1):
            start_time = self._snap_boundary(float(raw.get("start_time", previous_end)), valid_boundaries)
            end_time = self._snap_boundary(float(raw.get("end_time", start_time)), valid_boundaries)

            if index == 1:
                start_time = 0.0
            if start_time < previous_end:
                start_time = previous_end
            if end_time <= start_time:
                continue

            duration = round(end_time - start_time, 2)
            if (
                enforce_duration_limits
                and (
                    duration < self.config.min_segment_duration - 0.01
                    or duration > self.config.max_segment_duration + 0.01
                )
            ):
                continue

            segment_shots = self._slice_shots_by_time(parsed_shots, start_time, end_time)
            if not segment_shots:
                continue

            previous_end = end_time
            results.append(
                {
                    "segment_number": index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "split_reason": str(raw.get("split_reason") or "llm_planned"),
                    "title": str(raw.get("title") or ""),
                    "description": str(raw.get("description") or ""),
                    "key_actions": [str(item) for item in (raw.get("key_actions") or []) if str(item).strip()],
                    "key_dialogues": list(raw.get("key_dialogues") or []) if isinstance(raw.get("key_dialogues"), list) else [],
                    "continuity_from_prev": str(raw.get("continuity_from_prev") or ""),
                    "continuity_to_next": str(raw.get("continuity_to_next") or ""),
                    "prompt_focus": str(raw.get("prompt_focus") or ""),
                    "shots": segment_shots,
                }
            )

        if not results:
            return []

        last_end = round(results[-1]["end_time"], 2)
        total_duration = round(min(target_duration, parsed_shots[-1].end_time), 2)
        if abs(last_end - total_duration) > 1.0:
            return []

        for idx, item in enumerate(results, start=1):
            item["segment_number"] = idx
        return results

    def _rebalance_split_points(
        self,
        *,
        split_points: List[Dict[str, Any]],
        parsed_shots: List[ParsedShot],
        target_duration: float,
    ) -> List[Dict[str, Any]]:
        """
        优先把前段时长推近 max_segment_duration，避免出现 6s+7s 这类平均切短。

        目标形态更接近：
        - 10 + 3
        - 10 + 10 + 4
        而不是：
        - 6 + 7
        - 7 + 7 + 7
        """
        if len(split_points) < 2 or not parsed_shots:
            return split_points

        max_duration = float(self.config.max_segment_duration)
        min_duration = float(self.config.min_segment_duration)
        boundary_candidates = sorted(
            {
                round(shot.end_time, 2)
                for shot in parsed_shots
                if 0.0 < shot.end_time <= target_duration + 0.01
            }
        )

        rebalanced = [dict(point) for point in split_points]

        for index in range(len(rebalanced) - 1):
            current = rebalanced[index]
            nxt = rebalanced[index + 1]

            current_duration = float(current["duration"])
            next_duration = float(nxt["duration"])

            if current_duration >= max_duration - 0.5:
                continue

            combined_duration = current_duration + next_duration
            remaining_after_fill = combined_duration - max_duration

            if remaining_after_fill < min_duration - 0.01:
                continue

            preferred_end = round(float(current["start_time"]) + max_duration, 2)
            new_end = self._find_rebalance_boundary(
                boundaries=boundary_candidates,
                start_time=float(current["start_time"]),
                combined_end=float(nxt["end_time"]),
                preferred_end=preferred_end,
                min_duration=min_duration,
            )

            if new_end is None or new_end <= float(current["end_time"]) + 0.01:
                continue

            current_shots = self._slice_shots_by_time(parsed_shots, float(current["start_time"]), new_end)
            next_shots = self._slice_shots_by_time(parsed_shots, new_end, float(nxt["end_time"]))

            if not current_shots or not next_shots:
                continue

            new_current_duration = round(new_end - float(current["start_time"]), 2)
            new_next_duration = round(float(nxt["end_time"]) - new_end, 2)
            if new_current_duration < min_duration or new_next_duration < min_duration:
                continue

            current["end_time"] = new_end
            current["duration"] = new_current_duration
            current["shots"] = current_shots
            current["split_reason"] = f"{current.get('split_reason') or 'planned'}+rebalance_to_max"

            nxt["start_time"] = new_end
            nxt["duration"] = new_next_duration
            nxt["shots"] = next_shots
            nxt["split_reason"] = f"{nxt.get('split_reason') or 'planned'}+rebalance_remainder"

        for idx, item in enumerate(rebalanced, start=1):
            item["segment_number"] = idx
        return rebalanced

    def _find_rebalance_boundary(
        self,
        *,
        boundaries: List[float],
        start_time: float,
        combined_end: float,
        preferred_end: float,
        min_duration: float,
    ) -> Optional[float]:
        valid = [
            boundary
            for boundary in boundaries
            if boundary - start_time >= min_duration - 0.01
            and combined_end - boundary >= min_duration - 0.01
        ]
        if not valid:
            return None
        return min(valid, key=lambda boundary: (abs(boundary - preferred_end), -boundary))

    def _slice_shots_by_time(
        self,
        parsed_shots: List[ParsedShot],
        start_time: float,
        end_time: float,
    ) -> List[ParsedShot]:
        selected = [
            shot
            for shot in parsed_shots
            if shot.start_time >= start_time - 0.01 and shot.end_time <= end_time + 0.01
        ]
        return selected

    def _snap_boundary(self, value: float, valid_boundaries: set[float]) -> float:
        if not valid_boundaries:
            return round(value, 2)
        return min(valid_boundaries, key=lambda point: abs(point - round(value, 2)))

    async def _review_segments(
        self,
        *,
        script: str,
        segments: List[VideoSegment],
        target_duration: Optional[float],
    ) -> Dict[str, Any]:
        fallback_report = self._build_rule_based_validation_report(
            segments=segments,
            target_duration=target_duration,
        )
        if not segments:
            return fallback_report

        try:
            llm_report = await self._review_segments_with_llm(
                script=script,
                segments=segments,
                target_duration=target_duration,
            )
            if llm_report:
                return llm_report
        except Exception as exc:
            logger.warning("LLM segment review failed, fallback to rule validation: %s", exc)

        return fallback_report

    async def _auto_fix_segments_if_needed(
        self,
        *,
        script: str,
        analysis: Dict[str, Any],
        effective_target_duration: float,
        current_split_points: List[Dict[str, Any]],
        current_segments: List[VideoSegment],
        current_continuity_points: List[Dict[str, Any]],
        current_validation_report: Dict[str, Any],
        requested_target_duration: Optional[float],
    ) -> tuple[List[VideoSegment], List[Dict[str, Any]], Dict[str, Any]]:
        current_status = self._normalize_review_status(current_validation_report.get("status"))
        if current_status == "pass":
            return current_segments, current_continuity_points, current_validation_report

        parsed_shots: List[ParsedShot] = analysis.get("parsed_shots", []) or []
        if not parsed_shots:
            return current_segments, current_continuity_points, current_validation_report

        candidate_variants: List[tuple[str, List[Dict[str, Any]]]] = []

        llm_repaired_split_points = await self._repair_split_points_with_llm(
            script=script,
            parsed_shots=parsed_shots,
            current_segments=current_segments,
            current_validation_report=current_validation_report,
            target_duration=effective_target_duration,
        )
        if llm_repaired_split_points:
            candidate_variants.append(("llm_repair", llm_repaired_split_points))

        rule_repaired_split_points = self._repair_split_points_rule_based(
            analysis=analysis,
            target_duration=effective_target_duration,
        )
        if rule_repaired_split_points:
            if not self._split_points_equivalent(rule_repaired_split_points, current_split_points):
                candidate_variants.append(("rule_repair", rule_repaired_split_points))

        best_segments = current_segments
        best_continuity_points = current_continuity_points
        best_report = current_validation_report
        best_source: Optional[str] = None

        for source, split_points in candidate_variants:
            split_points = self._optimize_split_points_for_character_continuity(
                split_points=split_points,
                parsed_shots=parsed_shots,
                target_duration=effective_target_duration,
            )
            if self._split_points_equivalent(split_points, current_split_points):
                continue

            candidate_segments = await self._generate_segments(script, split_points)
            candidate_segments = self._annotate_segments_for_video_generation(
                segments=candidate_segments,
                parsed_shots=parsed_shots,
            )
            candidate_continuity_points = self._generate_continuity_points(candidate_segments)
            candidate_report = await self._review_segments(
                script=script,
                segments=candidate_segments,
                target_duration=requested_target_duration,
            )

            if self._is_validation_report_better(candidate_report, best_report):
                best_segments = candidate_segments
                best_continuity_points = candidate_continuity_points
                best_report = candidate_report
                best_source = source
                if self._normalize_review_status(candidate_report.get("status")) == "pass":
                    break

        if best_source is None:
            return current_segments, current_continuity_points, current_validation_report

        enriched_report = dict(best_report)
        enriched_report["auto_repair_applied"] = True
        enriched_report["auto_repair_source"] = best_source
        enriched_report["pre_repair_status"] = current_status
        enriched_report["pre_repair_summary"] = str(current_validation_report.get("summary") or "")
        repair_note = (
            f"系统已自动执行分段修复（{best_source}），并返回更优的拆分结果。"
        )
        existing_suggestions = self._normalize_string_list(enriched_report.get("suggestions"))
        enriched_report["suggestions"] = self._dedupe_text_items([repair_note, *existing_suggestions])

        logger.info(
            "Segment auto repair applied: source=%s before=%s after=%s",
            best_source,
            current_status,
            self._normalize_review_status(enriched_report.get("status")),
        )
        return best_segments, best_continuity_points, enriched_report

    async def _repair_split_points_with_llm(
        self,
        *,
        script: str,
        parsed_shots: List[ParsedShot],
        current_segments: List[VideoSegment],
        current_validation_report: Dict[str, Any],
        target_duration: float,
    ) -> List[Dict[str, Any]]:
        if not parsed_shots or not current_segments:
            return []

        candidate_boundaries = self._build_candidate_boundaries(parsed_shots, target_duration)
        timeline = self._build_shot_timeline_for_llm(parsed_shots, target_duration)
        current_segments_payload = [
            {
                "segment_number": segment.segment_number,
                "title": segment.title,
                "start_time": round(float(segment.start_time), 2),
                "end_time": round(float(segment.end_time), 2),
                "duration": round(float(segment.duration), 2),
                "description": segment.description,
                "key_actions": segment.key_actions,
                "key_dialogues": [
                    self._dialogue_display_text(dialogue)
                    for dialogue in segment.key_dialogues
                ],
                "continuity_from_prev": segment.continuity_from_prev,
                "continuity_to_next": segment.continuity_to_next,
                "prompt_focus": segment.prompt_focus,
            }
            for segment in current_segments
        ]

        system_prompt = f"""你是一位视频分段修复导演。你不会重写剧情，只会在原剧本镜头时间线基础上修复已有片段拆分结果。

修复目标：
1. 每个片段时长必须在 {self.config.min_segment_duration:.0f}-{self.config.max_segment_duration:.0f} 秒之间
2. 片段内容量要和时长匹配，避免在很短时长中塞入过多剧情
3. 片段之间时间必须连续，承接必须自然
4. 如果目标总时长存在，修复后总时长要尽量贴近目标
5. 不要改写剧情，不要新增不存在的情节，只调整分段边界并重写简洁的片段说明
6. 必须只使用候选边界时间点作为片段起止时间

输出必须是合法 JSON：
{{
  "segments": [
    {{
      "segment_number": 1,
      "start_time": 0.0,
      "end_time": 8.0,
      "title": "片段标题",
      "description": "片段描述",
      "key_actions": ["动作1"],
      "key_dialogues": ["对话1"],
      "continuity_from_prev": "",
      "continuity_to_next": "与下一段的衔接",
      "prompt_focus": "该段最重要的镜头重点",
      "split_reason": "修复原因"
    }}
  ]
}}

不要输出解释文字，不要输出 markdown 代码块。"""

        user_prompt = (
            f"完整剧本：\n{script[:7000]}\n\n"
            f"镜头时间线：\n{timeline}\n\n"
            f"候选边界：{json.dumps(candidate_boundaries, ensure_ascii=False)}\n\n"
            f"当前片段拆分：\n{json.dumps(current_segments_payload, ensure_ascii=False, indent=2)}\n\n"
            f"当前审核报告：\n{json.dumps(current_validation_report, ensure_ascii=False, indent=2)}\n\n"
            f"目标总时长：{target_duration:.1f} 秒。请直接输出修复后的 JSON。"
        )

        try:
            response = await self.llm.chat_completion(
                [
                    DoubaoMessage(role="system", content=system_prompt),
                    DoubaoMessage(role="user", content=user_prompt),
                ],
                temperature=0.2,
                max_tokens=2600,
                request_label="script_segment_repair",
            )
            payload = self._parse_llm_json(response.get_content().strip())
            raw_segments = payload.get("segments") or []
            return self._validate_llm_segments(
                raw_segments=raw_segments,
                parsed_shots=parsed_shots,
                target_duration=target_duration,
                candidate_boundaries=candidate_boundaries,
            )
        except Exception as exc:
            logger.warning("LLM segment repair failed: %s", exc)
            return []

    def _repair_split_points_rule_based(
        self,
        *,
        analysis: Dict[str, Any],
        target_duration: float,
    ) -> List[Dict[str, Any]]:
        recalculated = self._calculate_split_points(analysis, target_duration)
        parsed_shots: List[ParsedShot] = analysis.get("parsed_shots", []) or []
        if not recalculated or not parsed_shots:
            return recalculated
        rebalanced = self._rebalance_split_points(
            split_points=recalculated,
            parsed_shots=parsed_shots,
            target_duration=target_duration,
        )
        return self._optimize_split_points_for_character_continuity(
            split_points=rebalanced,
            parsed_shots=parsed_shots,
            target_duration=target_duration,
        )

    def _split_points_equivalent(
        self,
        left: List[Dict[str, Any]],
        right: List[Dict[str, Any]],
    ) -> bool:
        if len(left) != len(right):
            return False
        for left_item, right_item in zip(left, right):
            if abs(float(left_item.get("start_time", 0.0)) - float(right_item.get("start_time", 0.0))) > 0.01:
                return False
            if abs(float(left_item.get("end_time", 0.0)) - float(right_item.get("end_time", 0.0))) > 0.01:
                return False
        return True

    def _is_validation_report_better(
        self,
        candidate: Dict[str, Any],
        baseline: Dict[str, Any],
    ) -> bool:
        return self._validation_report_score(candidate) > self._validation_report_score(baseline)

    def _validation_report_score(self, report: Dict[str, Any]) -> tuple[int, int, int]:
        status_rank = {
            "fail": 0,
            "warning": 1,
            "pass": 2,
        }
        status = self._normalize_review_status(report.get("status"))
        issues_count = len(self._normalize_string_list(report.get("issues")))
        segment_problem_count = sum(
            1
            for item in (report.get("segment_reviews") or [])
            if isinstance(item, dict) and self._normalize_review_status(item.get("status")) != "pass"
        )
        return (
            status_rank.get(status, 0),
            -issues_count,
            -segment_problem_count,
        )

    async def _review_segments_with_llm(
        self,
        *,
        script: str,
        segments: List[VideoSegment],
        target_duration: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        segment_payload = [
            {
                "segment_number": segment.segment_number,
                "title": segment.title,
                "start_time": round(float(segment.start_time), 2),
                "end_time": round(float(segment.end_time), 2),
                "duration": round(float(segment.duration), 2),
                "description": segment.description,
                "shots_summary": segment.shots_summary,
                "key_actions": segment.key_actions,
                "key_dialogues": [
                    self._dialogue_display_text(dialogue)
                    for dialogue in segment.key_dialogues
                ],
                "continuity_from_prev": segment.continuity_from_prev,
                "continuity_to_next": segment.continuity_to_next,
                "prompt_focus": segment.prompt_focus,
                "video_prompt": segment.video_prompt,
            }
            for segment in segments
        ]

        system_prompt = f"""你是一位专业的短剧后期总导演，负责审核“剧本拆分成视频片段”的结果是否适合进入视频生成阶段。

审核重点：
1. 每个片段时长必须不超过 {self.config.max_segment_duration:.0f} 秒
2. 片段内容量必须与该片段时长匹配，避免剧情内容明显过多但时长过短
3. 多个片段之间要具备剧情连续性、动作衔接性、情绪延续性
4. 如果给了目标总时长，要判断拆分后的总时长是否合理贴合目标
5. 输出要指出问题最严重的片段，并给出明确修改建议
6. 如果有新角色首次正式登场，审核时要判断该角色是否被单独起段，是否适合额外生成角色锚定首帧
7. 除最后一段外，优先检查每段结尾是否仍保留下一段会继续出现的角色，避免下一段角色漂移
8. 优先检查每一段是否存在“首镜头未出现的角色在段内中途入场”，如有则应建议在该角色首次出镜处切段
9. 重点审核每一段的 video_prompt 是否真的适合视频模型：要像单次生成指令，能看出首帧、动作推进、镜头语言与结尾承接，而不是结构化摘要或调试字段

输出必须是合法 JSON，格式：
{{
  "status": "pass|warning|fail",
  "summary": "整体结论",
  "checks": [
    {{
      "code": "duration_limit",
      "label": "单片段时长限制",
      "status": "pass|warning|fail",
      "detail": "说明"
    }},
    {{
      "code": "content_fit",
      "label": "片段内容与时长匹配",
      "status": "pass|warning|fail",
      "detail": "说明"
    }},
    {{
      "code": "video_prompt_fit",
      "label": "片段 Prompt 可生成性",
      "status": "pass|warning|fail",
      "detail": "说明"
    }},
    {{
      "code": "continuity",
      "label": "多段剧情连贯性",
      "status": "pass|warning|fail",
      "detail": "说明"
    }},
    {{
      "code": "target_total_duration",
      "label": "总时长目标匹配",
      "status": "pass|warning|fail",
      "detail": "说明"
    }}
  ],
  "issues": ["全局问题1"],
  "suggestions": ["全局建议1"],
  "segment_reviews": [
    {{
      "segment_number": 1,
      "status": "pass|warning|fail",
      "summary": "这一段的审核结论",
      "issues": ["问题1"],
      "suggestions": ["建议1"]
    }}
  ]
}}

不要输出解释文字，不要输出 markdown 代码块。"""

        user_prompt = (
            f"完整剧本：\n{script[:7000]}\n\n"
            f"目标总时长：{target_duration if target_duration is not None else '未指定'}\n"
            f"拆分结果：\n{json.dumps(segment_payload, ensure_ascii=False, indent=2)}\n\n"
            "请按要求输出 JSON 审核报告。"
        )

        response = await self.llm.chat_completion(
            [
                DoubaoMessage(role="system", content=system_prompt),
                DoubaoMessage(role="user", content=user_prompt),
            ],
            temperature=0.2,
            max_tokens=2200,
            request_label="script_segment_review",
        )
        parsed = self._parse_llm_json(response.get_content().strip())
        return self._normalize_validation_report(
            report=parsed,
            segments=segments,
            target_duration=target_duration,
            source="llm",
        )

    def _build_rule_based_validation_report(
        self,
        *,
        segments: List[VideoSegment],
        target_duration: Optional[float],
    ) -> Dict[str, Any]:
        checks: List[Dict[str, str]] = []
        issues: List[str] = []
        suggestions: List[str] = []
        segment_reviews: List[Dict[str, Any]] = []

        duration_check_status = "pass"
        for segment in segments:
            if float(segment.duration) > self.config.max_segment_duration + 0.01:
                duration_check_status = "fail"
                issues.append(
                    f"片段 {segment.segment_number} 时长 {float(segment.duration):.1f}s，超过 {self.config.max_segment_duration:.0f}s 限制。"
                )

        checks.append(
            {
                "code": "duration_limit",
                "label": "单片段时长限制",
                "status": duration_check_status,
                "detail": "所有片段都在时长限制内。" if duration_check_status == "pass" else "存在片段时长超过限制。",
            }
        )

        content_check_status = "pass"
        for index, segment in enumerate(segments):
            segment_issues = self._estimate_content_fit_issues(segment)
            status = "pass"
            summary = "片段内容量与时长基本匹配。"
            if segment_issues:
                status = "warning"
                content_check_status = "warning" if content_check_status == "pass" else content_check_status
                summary = "片段内容密度偏高，建议压缩剧情或拉长时长。"
            if segment.prefer_character_handoff_end_frame and not segment.ending_contains_handoff_characters:
                status = "warning"
                content_check_status = "warning" if content_check_status == "pass" else content_check_status
                segment_issues.append("该段结尾镜头未保留下一段仍会继续出现的角色，下一段角色连续性存在漂移风险。")
            if segment.late_entry_character_profile_ids:
                status = "warning"
                content_check_status = "warning" if content_check_status == "pass" else content_check_status
                segment_issues.append(
                    "该段存在首镜头未出现的角色在段内中途入场，建议从这些角色首次出镜的镜头开始新起一段："
                    + "、".join(segment.late_entry_character_profile_ids)
                )
            if index > 0 and segment.pre_generate_start_frame and segment.start_frame_generation_reason == "new_character_entry":
                summary = "该段被识别为新角色正式登场段，已建议额外预生成首帧稳定角色造型。"
            segment_reviews.append(
                {
                    "segment_number": segment.segment_number,
                    "title": segment.title,
                    "duration": round(float(segment.duration), 2),
                    "status": status,
                    "summary": summary,
                    "issues": segment_issues,
                    "suggestions": (
                        ["减少同段动作/对白数量，或将该段拆成更清晰的小节奏。"]
                        if segment_issues
                        else []
                    )
                    + (
                        ["把该段结尾调整为下一段仍会继续出现的角色仍在画面内的镜头，方便下一段承接。"]
                        if segment.prefer_character_handoff_end_frame and not segment.ending_contains_handoff_characters
                        else []
                    )
                    + (
                        ["将该段中途入场的角色改为从新片段首镜头开始出镜，避免首帧未出现角色在段内突然进入。"]
                        if segment.late_entry_character_profile_ids
                        else []
                    )
                    + (
                        ["保留该段的额外首帧生成，用于新角色首次正式出场时稳定造型。"]
                        if segment.pre_generate_start_frame and segment.start_frame_generation_reason == "new_character_entry"
                        else []
                    ),
                }
            )

        checks.append(
            {
                "code": "content_fit",
                "label": "片段内容与时长匹配",
                "status": content_check_status,
                "detail": "片段内容量整体可控。"
                if content_check_status == "pass"
                else "存在片段在当前时长下承载内容偏多的情况。",
            }
        )

        prompt_fit_status = "pass"
        for segment_review, segment in zip(segment_reviews, segments):
            prompt_issues = self._estimate_video_prompt_fit_issues(segment)
            if not prompt_issues:
                continue
            if prompt_fit_status == "pass":
                prompt_fit_status = "warning"
            if segment_review["status"] == "pass":
                segment_review["status"] = "warning"
                segment_review["summary"] = "该段的 video_prompt 仍偏像摘要，建议改成更像单次视频生成指令。"
            segment_review["issues"] = self._dedupe_text_items([*segment_review["issues"], *prompt_issues])
            segment_review["suggestions"] = self._dedupe_text_items(
                [
                    *segment_review["suggestions"],
                    "把该段 prompt 改成单段视频生成指令，明确首帧主体、动作推进、镜头运动和结尾停点。",
                ]
            )

        checks.append(
            {
                "code": "video_prompt_fit",
                "label": "片段 Prompt 可生成性",
                "status": prompt_fit_status,
                "detail": "各片段 video_prompt 基本可直接用于视频模型生成。"
                if prompt_fit_status == "pass"
                else "存在 video_prompt 仍像摘要或调试字段，不够像单次视频生成指令的片段。",
            }
        )

        continuity_status = "pass"
        for index, segment in enumerate(segments):
            if index == 0:
                continue
            previous = segments[index - 1]
            if abs(float(segment.start_time) - float(previous.end_time)) > 0.1:
                continuity_status = "fail"
                issues.append(
                    f"片段 {previous.segment_number} 与片段 {segment.segment_number} 时间边界不连续："
                    f"{float(previous.end_time):.1f}s -> {float(segment.start_time):.1f}s。"
                )
            elif not (segment.continuity_from_prev or previous.continuity_to_next):
                if continuity_status == "pass":
                    continuity_status = "warning"
                issues.append(
                    f"片段 {previous.segment_number} 与片段 {segment.segment_number} 缺少明确的承接说明。"
                )

        checks.append(
            {
                "code": "continuity",
                "label": "多段剧情连贯性",
                "status": continuity_status,
                "detail": "片段之间的时间与承接描述基本连贯。"
                if continuity_status == "pass"
                else "部分片段之间的衔接还不够清晰。",
            }
        )

        actual_total_duration = round(sum(float(segment.duration) for segment in segments), 2)
        target_status = "pass"
        target_detail = "未设置目标总时长，跳过该项。"
        if target_duration is not None:
            tolerance = self._target_duration_tolerance(target_duration)
            delta = abs(actual_total_duration - float(target_duration))
            if delta > tolerance * 1.5:
                target_status = "fail"
            elif delta > tolerance:
                target_status = "warning"
            target_detail = (
                f"拆分总时长 {actual_total_duration:.1f}s，目标 {float(target_duration):.1f}s，"
                f"偏差 {delta:.1f}s。"
            )
            if target_status != "pass":
                issues.append(target_detail)
                suggestions.append("重新拆分时优先调整前中段时长分配，使总时长更贴近目标。")

        checks.append(
            {
                "code": "target_total_duration",
                "label": "总时长目标匹配",
                "status": target_status,
                "detail": target_detail,
            }
        )

        if not suggestions and any(check["status"] != "pass" for check in checks):
            suggestions.append("根据审核报告调整片段划分，再进入首尾帧生成。")

        overall_status = self._merge_statuses(
            [check["status"] for check in checks] + [item["status"] for item in segment_reviews]
        )
        summary = self._build_validation_summary(overall_status, issues)

        return {
            "status": overall_status,
            "summary": summary,
            "checks": checks,
            "issues": self._dedupe_text_items(issues),
            "suggestions": self._dedupe_text_items(suggestions),
            "segment_reviews": segment_reviews,
            "source": "rules",
            "target_total_duration": float(target_duration) if target_duration is not None else None,
            "actual_total_duration": actual_total_duration,
        }

    def _normalize_validation_report(
        self,
        *,
        report: Dict[str, Any],
        segments: List[VideoSegment],
        target_duration: Optional[float],
        source: str,
    ) -> Dict[str, Any]:
        base_report = self._build_rule_based_validation_report(
            segments=segments,
            target_duration=target_duration,
        )
        allowed_codes = {
            "duration_limit": "单片段时长限制",
            "content_fit": "片段内容与时长匹配",
            "video_prompt_fit": "片段 Prompt 可生成性",
            "continuity": "多段剧情连贯性",
            "target_total_duration": "总时长目标匹配",
        }

        raw_checks = report.get("checks") if isinstance(report.get("checks"), list) else []
        normalized_checks: List[Dict[str, str]] = []
        raw_checks_by_code: Dict[str, Dict[str, Any]] = {}
        for item in raw_checks:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if code in allowed_codes:
                raw_checks_by_code[code] = item

        for base_check in base_report["checks"]:
            code = str(base_check["code"])
            raw_item = raw_checks_by_code.get(code, {})
            normalized_checks.append(
                {
                    "code": code,
                    "label": allowed_codes[code],
                    "status": self._normalize_review_status(raw_item.get("status"), fallback=base_check["status"]),
                    "detail": str(raw_item.get("detail") or base_check["detail"]),
                }
            )

        raw_segment_reviews = report.get("segment_reviews") if isinstance(report.get("segment_reviews"), list) else []
        raw_segment_map: Dict[int, Dict[str, Any]] = {}
        for item in raw_segment_reviews:
            if not isinstance(item, dict):
                continue
            try:
                segment_number = int(item.get("segment_number"))
            except (TypeError, ValueError):
                continue
            raw_segment_map[segment_number] = item

        base_segment_map = {
            int(item["segment_number"]): item
            for item in base_report["segment_reviews"]
            if isinstance(item, dict) and item.get("segment_number") is not None
        }
        normalized_segment_reviews: List[Dict[str, Any]] = []
        for segment in segments:
            base_item = base_segment_map.get(segment.segment_number, {})
            raw_item = raw_segment_map.get(segment.segment_number, {})
            normalized_segment_reviews.append(
                {
                    "segment_number": segment.segment_number,
                    "title": segment.title,
                    "duration": round(float(segment.duration), 2),
                    "status": self._normalize_review_status(raw_item.get("status"), fallback=base_item.get("status", "pass")),
                    "summary": str(raw_item.get("summary") or base_item.get("summary") or "该片段可进入下一步。"),
                    "issues": self._normalize_string_list(raw_item.get("issues") or base_item.get("issues")),
                    "suggestions": self._normalize_string_list(raw_item.get("suggestions") or base_item.get("suggestions")),
                }
            )

        overall_status = self._normalize_review_status(
            report.get("status"),
            fallback=self._merge_statuses(
                [check["status"] for check in normalized_checks] + [item["status"] for item in normalized_segment_reviews]
            ),
        )
        summary = str(report.get("summary") or self._build_validation_summary(overall_status, base_report["issues"]))

        return {
            "status": overall_status,
            "summary": summary,
            "checks": normalized_checks,
            "issues": self._normalize_string_list(report.get("issues") or base_report["issues"]),
            "suggestions": self._normalize_string_list(report.get("suggestions") or base_report["suggestions"]),
            "segment_reviews": normalized_segment_reviews,
            "source": source,
            "target_total_duration": float(target_duration) if target_duration is not None else None,
            "actual_total_duration": round(sum(float(segment.duration) for segment in segments), 2),
        }

    def _estimate_content_fit_issues(self, segment: VideoSegment) -> List[str]:
        issues: List[str] = []
        description_units = len((segment.description or "").strip()) / 26.0
        summary_units = len((segment.shots_summary or "").strip()) / 36.0
        action_units = len(segment.key_actions) * 1.4
        dialogue_units = len(segment.key_dialogues) * 1.2
        density_score = (description_units + summary_units + action_units + dialogue_units) / max(float(segment.duration), 1.0)

        if float(segment.duration) <= 4.0 and density_score >= 3.2:
            issues.append("该片段时长偏短，但承载的剧情信息明显偏多。")
        elif density_score >= 4.2:
            issues.append("该片段信息密度过高，视频模型可能无法在当前时长内稳定表达。")

        if len(segment.key_actions) + len(segment.key_dialogues) >= 6 and float(segment.duration) <= 5.0:
            issues.append("单段动作和对白节点过多，建议进一步拆分或压缩。")

        return issues

    def _estimate_video_prompt_fit_issues(self, segment: VideoSegment) -> List[str]:
        prompt = str(segment.video_prompt or "").strip()
        if not prompt:
            return ["该片段缺少 video_prompt，无法直接进入视频生成。"]

        issues: List[str] = []
        normalized = prompt.lower()
        meta_keywords = (
            "time window",
            "scene profile",
            "character profile ids",
            "spoken lines",
            "start_time",
            "end_time",
            "片段时间",
            "片段标题",
            "片段描述",
            "镜头时间线",
        )
        if any(keyword in normalized or keyword in prompt for keyword in meta_keywords):
            issues.append("video_prompt 仍包含结构化摘要或调试字段，更像给人读的说明，不像给视频模型的生成指令。")

        start_keywords = ("首帧", "开场", "起始", "一开始", "画面开始", "opening frame", "opening shot", "start frame")
        if not any(keyword in normalized or keyword in prompt for keyword in start_keywords):
            issues.append("video_prompt 缺少明确首帧/开场状态，视频模型较难稳定起画。")

        progression_keywords = ("动作推进", "随后", "接着", "然后", "先", "再", "最终", "结尾", "progression", "then", "finally")
        if len(segment.key_actions) + len(segment.key_dialogues) >= 2 and not any(
            keyword in normalized or keyword in prompt for keyword in progression_keywords
        ):
            issues.append("video_prompt 没有明确动作推进或段内节奏，视频模型较难理解这一段如何发展。")

        camera_keywords = ("镜头", "运镜", "推近", "跟拍", "摇镜", "移镜", "景别", "camera", "tracking", "dolly", "pan")
        if not any(keyword in normalized or keyword in prompt for keyword in camera_keywords):
            issues.append("video_prompt 缺少镜头语言约束，不利于视频模型稳定生成画面组织。")

        return self._dedupe_text_items(issues)

    def _target_duration_tolerance(self, target_duration: float) -> float:
        return max(1.0, min(3.0, float(target_duration) * 0.1))

    def _normalize_review_status(self, value: Any, *, fallback: str = "pass") -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"pass", "warning", "fail"}:
            return normalized
        return fallback

    def _merge_statuses(self, statuses: List[str]) -> str:
        normalized = [self._normalize_review_status(item) for item in statuses]
        if "fail" in normalized:
            return "fail"
        if "warning" in normalized:
            return "warning"
        return "pass"

    def _normalize_string_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return self._dedupe_text_items([str(item).strip() for item in value if str(item).strip()])

    def _dedupe_text_items(self, items: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _build_validation_summary(self, status: str, issues: List[str]) -> str:
        if status == "fail":
            return issues[0] if issues else "片段审核未通过，建议先调整拆分结果。"
        if status == "warning":
            return issues[0] if issues else "片段审核存在风险，建议人工确认后再继续。"
        return "片段拆分通过二次校验，可继续生成首尾帧。"

    async def _generate_video_prompt_with_llm(
        self,
        *,
        segment_script: str,
        point: Dict[str, Any],
        segment_shots: List[ParsedShot],
        has_previous: bool,
        has_next: bool,
    ) -> Optional[Dict[str, Any]]:
        shot_timeline = self._build_shot_timeline_for_llm(segment_shots, point["end_time"])
        prompt_focus = str(point.get("prompt_focus") or "")
        opening_clause = self._build_segment_opening_clause(segment_shots)
        action_progression = self._build_segment_action_progression(segment_shots)
        camera_clause = self._build_segment_camera_clause(segment_shots)
        ending_clause = self._build_segment_ending_clause(segment_shots)
        dialogue_clause = self._build_segment_dialogue_clause(segment_shots)

        system_prompt = """你是一位 AI 视频导演，负责把一个视频片段整理成可直接喂给视频生成模型的高质量 Prompt。

要求：
1. Prompt 必须像“单次视频生成指令”，而不是剧情摘要、字段清单或镜头笔记
2. 必须明确首帧/开场状态、主体角色、场景环境、动作推进、镜头运动、结尾停点
3. 要把多个镜头信息整理成一个连续可生成的视频段落，不要逐条复述“镜头1/镜头2”
4. 重点强调角色一致性、空间连续性、动作连贯、镜头语言、光线氛围
5. 如果存在上下段衔接，需要在 prompt 里明确“如何接上段、如何留给下段”
6. 不要输出调试字段，不要出现 start_time、end_time、scene profile、character profile ids、spoken lines 这类元信息标签
7. 输出 JSON：
{
  "prompt": "...",
  "negative_prompt": "...",
  "config": {
    "style": "cinematic_realistic"
  }
}
只输出 JSON，不要额外解释。"""

        user_prompt = (
            f"片段时间：{point['start_time']:.1f}s - {point['end_time']:.1f}s\n"
            f"片段标题：{point.get('title') or ''}\n"
            f"片段描述：{point.get('description') or ''}\n"
            f"前段衔接：{'是' if has_previous else '否'}\n"
            f"后段衔接：{'是' if has_next else '否'}\n"
            f"重点方向：{prompt_focus or '无'}\n\n"
            f"建议首帧信息：{opening_clause or '无'}\n"
            f"建议动作推进：{action_progression or '无'}\n"
            f"建议镜头设计：{camera_clause or '无'}\n"
            f"建议结尾停点：{ending_clause or '无'}\n"
            f"对白重点：{dialogue_clause or '无'}\n\n"
            f"片段镜头时间线：\n{shot_timeline}\n\n"
            f"片段文本：\n{segment_script[:4000]}"
        )

        try:
            messages = [
                DoubaoMessage(role="system", content=system_prompt),
                DoubaoMessage(role="user", content=user_prompt),
            ]
            response = await self.llm.chat_completion(
                messages,
                temperature=0.2,
                max_tokens=1800,
            )
            parsed = self._parse_llm_json(response.get_content().strip())
            prompt = str(parsed.get("prompt") or "").strip()
            if not prompt:
                return None
            negative_prompt = str(parsed.get("negative_prompt") or "").strip()
            config = dict(parsed.get("config") or {})
            config.setdefault("duration", min(point["duration"], self.config.max_segment_duration))
            config.setdefault("aspect_ratio", "16:9")
            config.setdefault("style", "cinematic_realistic")
            config.setdefault("source", "llm-script-splitter")
            return {
                "prompt": prompt,
                "negative_prompt": negative_prompt or (
                    "卡通化, 二次元, 信息图排版, 分屏, 多宫格, 字幕烧录, 水印, 低清晰度, 模糊, 解剖错误, "
                    "角色漂移, 服装突变, 跳切, 重复动作循环, 镜头逻辑断裂, 空间关系错误"
                ),
                "config": config,
                "segment_script": segment_script,
            }
        except Exception as exc:
            logger.warning("LLM video prompt generation failed for segment %s: %s", point.get("segment_number"), exc)
            return None

    def _parse_llm_json(self, content: str) -> Dict[str, Any]:
        candidates = self._build_json_candidates(content)
        parse_errors: List[str] = []

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"json:{exc}")

        for candidate in candidates:
            python_like = self._convert_json_literals_to_python(candidate)
            try:
                parsed = ast.literal_eval(python_like)
            except (SyntaxError, ValueError) as exc:
                parse_errors.append(f"literal_eval:{exc}")
                continue
            if isinstance(parsed, dict):
                return parsed

        raise ValueError(f"无法解析 LLM JSON。errors={parse_errors[:4]}")

    def _build_json_candidates(self, content: str) -> List[str]:
        raw = content.strip()
        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        object_match = re.search(r"\{.*\}", raw, re.DOTALL)
        candidates = [raw]
        if fenced_match:
            candidates.append(fenced_match.group(1))
        if object_match:
            candidates.append(object_match.group(0))

        normalized_candidates: List[str] = []
        seen = set()
        for value in candidates:
            value = value.strip()
            if not value:
                continue
            variants = [
                value,
                re.sub(r"/\*.*?\*/", "", value, flags=re.DOTALL).strip(),
                re.sub(r",(\s*[}\]])", r"\1", value).strip(),
            ]
            for variant in variants:
                if variant and variant not in seen:
                    seen.add(variant)
                    normalized_candidates.append(variant)
        return normalized_candidates

    def _convert_json_literals_to_python(self, value: str) -> str:
        converted = re.sub(r"\btrue\b", "True", value)
        converted = re.sub(r"\bfalse\b", "False", converted)
        converted = re.sub(r"\bnull\b", "None", converted)
        return converted


# 便捷函数
async def split_script(
    script: str,
    max_segment_duration: float = 10.0,
    target_duration: Optional[float] = None
) -> SplitResult:
    """
    拆分剧本的便捷函数
    
    Args:
        script: 完整剧本文本
        max_segment_duration: 每个片段最大时长（默认10秒）
        target_duration: 目标总时长（可选）
    
    Returns:
        SplitResult: 拆分结果
    """
    config = SplitConfig(
        max_segment_duration=min(float(max_segment_duration), MAX_VIDEO_SEGMENT_DURATION),
        min_segment_duration=3.0,
        prefer_scene_boundary=True,
        preserve_dialogue=True,
        smooth_transition=True
    )
    
    splitter = ScriptSplitter(config)
    return await splitter.split_script(
        script=script,
        target_duration=target_duration
    )


# 测试代码
if __name__ == "__main__":
    async def test():
        # 测试剧本
        test_script = """
        【场景1：潜入】0-15秒
        威龙蹲伏在废弃工厂阴影中，眼神锐利，表情专注。
        他通过耳机低声说："蛊，就位了吗？"（低语，紧张）
        耳机传来蛊冷静的声音："就位。前方两名守卫。"
        威龙微微点头，举起虎蹲炮瞄准，动作流畅专业。
        
        【场景2：交火】15-35秒
        突然，警报响起！红灯闪烁。
        威龙果断开火，虎蹲炮轰鸣，炮口火光闪现。
        "发现敌人！"威龙大喊（大喊，紧迫）
        蛊从侧面冲出，致盲毒雾瞬间弥漫，紫色烟雾扩散。
        "后退！找掩体！"威龙命令（命令语气，坚决）
        同时翻滚躲避子弹，动作敏捷。
        两人在浓烟中背靠背，枪声四起，火光闪烁。
        
        【场景3：撤离】35-50秒
        敌人暂时被压制，威龙看向蛊："走！撤离！"（急促但清晰）
        蛊点头，眼神坚定，两人交替掩护向出口移动。
        威龙最后一个撤出，回望燃烧的工厂，眼神坚定，表情凝重。
        """
        
        print("=" * 70)
        print("测试剧本拆分")
        print("=" * 70)
        print(f"\n输入剧本长度: {len(test_script)} 字符\n")
        
        result = await split_script(
            script=test_script,
            max_segment_duration=10.0
        )
        
        print(f"\n✅ 拆分完成!")
        print(f"总时长: {result.total_duration:.1f}秒")
        print(f"片段数: {result.segment_count}")
        print(f"\n生成了 {len(result.segments)} 个视频片段:\n")
        
        for seg in result.segments:
            print(f"  片段 {seg.segment_number}: {seg.title}")
            print(f"    时长: {seg.duration:.1f}秒 ({seg.start_time:.1f}s - {seg.end_time:.1f}s)")
            print(f"    描述: {seg.description[:80]}...")
            print(f"    Prompt: {seg.video_prompt[:100]}...")
            print()
        
        if result.continuity_points:
            print(f"\n衔接点信息 ({len(result.continuity_points)} 个):")
            for point in result.continuity_points[:3]:  # 只显示前3个
                print(f"  片段 {point['between_segments'][0]} → 片段 {point['between_segments'][1]}")
                print(f"    建议转场: {point['recommended_transition']}")
    
    asyncio.run(test())
