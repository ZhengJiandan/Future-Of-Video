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
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import logging

from app.services.doubao_llm import DoubaoLLM, DoubaoMessage

logger = logging.getLogger(__name__)


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
    key_dialogues: List[str] = field(default_factory=list)  # 关键对话
    
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
    
    # 结果
    video_url: str = ""                   # 生成的视频URL
    status: str = "pending"               # 状态
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)


@dataclass
class SplitConfig:
    """剧本拆分配置"""
    max_segment_duration: float = 10.0     # 每个片段最大时长（秒）
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
            "continuity_points": self.continuity_points
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


class ScriptSplitter:
    """
    剧本拆分器 - 核心类
    负责将长剧本智能拆分为多个短视频片段
    """
    
    def __init__(self, config: Optional[SplitConfig] = None):
        self.config = config or SplitConfig()
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
        
        # 步骤3: 生成分段
        logger.info("步骤3: 生成视频片段...")
        segments = await self._generate_segments(script, split_points)
        
        # 步骤4: 生成衔接信息
        logger.info("步骤4: 生成衔接信息...")
        continuity_points = self._generate_continuity_points(segments)
        
        # 组装结果
        total_duration = sum(seg.duration for seg in segments)
        result = SplitResult(
            original_script=script,
            total_duration=total_duration,
            segment_count=len(segments),
            segments=segments,
            config=self.config,
            continuity_points=continuity_points
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
        
        for i, point in enumerate(split_points):
            segment_shots: List[ParsedShot] = point.get("shots", []) or []
            # 提取该片段对应的剧本内容
            segment_script = self._extract_segment_script(
                script,
                point["start_time"],
                point["end_time"],
                segment_shots,
            )
            key_actions = self._collect_unique_items([action for shot in segment_shots for action in shot.actions], limit=6)
            key_dialogues = self._collect_unique_items([dialogue for shot in segment_shots for dialogue in shot.dialogues], limit=4)
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
            llm_key_dialogues = self._collect_unique_items(point.get("key_dialogues", []) or [], limit=4)
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
                character_profile_ids=self._collect_unique_items(
                    [profile_id for shot in segment_shots for profile_id in shot.character_profile_ids if profile_id],
                    limit=12,
                ),
                character_profile_versions=self._merge_profile_versions(segment_shots),
                prompt_focus=str(point.get("prompt_focus") or self._build_segment_prompt_focus(segment_shots)),
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
        bound_character_ids = self._collect_unique_items(
            [profile_id for shot in segment_shots for profile_id in shot.character_profile_ids if profile_id],
            limit=8,
        )

        prompt_parts = [
            "cinematic tactical action sequence",
            f"time window {point['start_time']:.1f}s to {point['end_time']:.1f}s",
            f"scene {first.scene_title}" if first and first.scene_title else "",
            f"scene profile {first.scene_profile_id}" if first and first.scene_profile_id else "",
            f"location {', '.join(locations)}" if locations else "",
            f"characters {', '.join(characters)}" if characters else "",
            f"character profile ids {', '.join(bound_character_ids)}" if bound_character_ids else "",
            f"camera language {', '.join(movements)}" if movements else "",
            f"lighting {', '.join(lighting)}" if lighting else "",
            f"atmosphere {', '.join(atmosphere)}" if atmosphere else "",
            f"focus {prompt_focus}" if prompt_focus else "",
            f"key visuals {'; '.join(shot_descriptions)}" if shot_descriptions else "",
            f"key actions {'; '.join(actions)}" if actions else "",
            f"spoken lines {'; '.join(dialogues)}" if dialogues else "",
            "preserve character identity consistency",
            "high detail, coherent motion, cinematic realism, 4k, professional composition",
        ]
        if has_previous:
            prompt_parts.append("continuing naturally from the previous segment")
        if has_next:
            prompt_parts.append("ending with a clear transition into the next segment")

        prompt = ", ".join(part for part in prompt_parts if part)

        return {
            "prompt": prompt,
            "negative_prompt": "cartoon, anime, duplicate shot composition, repeated action loop, low quality, blurry, distorted anatomy, broken continuity, watermark, subtitle burn-in",
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
4. 每个片段内部的镜头必须形成完整的小节奏，适合单段视频生成
5. 必须只使用候选边界中的时间点作为片段起止时间
6. 输出每个片段的优化信息：标题、片段描述、关键动作、关键对话、与前后片段衔接说明、该片段视频生成 prompt_focus
7. 除最后一个片段外，不要把片段平均切短。像 6 秒 + 7 秒 这种拆法不理想，应优先改成接近 10 秒 + 剩余片段时长
8. 如果总时长有余量，优先让前面的片段更接近 10 秒，最后一个片段再承担剩余的 3-9 秒

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
            lines.append(
                f"{shot.start_time:.1f}-{shot.end_time:.1f}s | 场景{shot.scene_number} {shot.scene_title} | "
                f"镜头{shot.shot_number} | {shot.description or '无描述'} | 动作:{actions} | 对话:{dialogues}"
            )
        return "\n".join(lines)

    def _validate_llm_segments(
        self,
        *,
        raw_segments: List[Dict[str, Any]],
        parsed_shots: List[ParsedShot],
        target_duration: float,
        candidate_boundaries: List[float],
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
            if duration < self.config.min_segment_duration - 0.01 or duration > self.config.max_segment_duration + 0.5:
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
                    "key_dialogues": [str(item) for item in (raw.get("key_dialogues") or []) if str(item).strip()],
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

        system_prompt = """你是一位 AI 视频导演，负责把一个视频片段整理成更适合视频生成模型的高质量 Prompt。

要求：
1. Prompt 要体现片段内部镜头之间的动作连接和情绪推进
2. 不要简单罗列镜头，要把片段整理成一个连续可生成的视频段落
3. 重点强调角色一致性、空间连续性、动作连贯、镜头语言、光线氛围
4. 输出 JSON：
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
                temperature=0.35,
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
                "negative_prompt": negative_prompt or "cartoon, anime, repeated action loop, low quality, blurry, distorted anatomy, broken continuity, watermark, subtitle burn-in",
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
        max_segment_duration=max_segment_duration,
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
