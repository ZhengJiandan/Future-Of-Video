#!/usr/bin/env python3
"""Profile-constrained script generator for the active pipeline."""

from __future__ import annotations

import ast
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.core.config import settings
from app.core.provider_keys import MissingProviderConfigError
from app.services.doubao_llm import DoubaoLLM, DoubaoMessage

logger = logging.getLogger(__name__)

SHOT_LATE_ENTRY_KEYWORDS = (
    "走入",
    "走进",
    "进入",
    "进来",
    "闯入",
    "冲入",
    "跑入",
    "跑进",
    "推门而入",
    "现身",
    "出现",
    "突然出现",
    "冒出",
    "到来",
    "赶来",
    "加入画面",
    "进入画面",
    "出现在画面",
)


@dataclass
class CharacterInfo:
    name: str
    profile_id: str = ""
    profile_version: int = 1
    category: str = ""
    role_type: str = ""
    archetype: str = ""
    appearance: str = ""
    personality: str = ""
    current_emotion: str = ""
    facial_expression: str = ""
    body_language: str = ""
    current_pose: str = ""
    speaking_style: str = ""
    common_actions: str = ""
    llm_summary: str = ""
    must_keep: List[str] = field(default_factory=list)
    forbidden: List[str] = field(default_factory=list)
    equipment: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)


@dataclass
class DialogueLine:
    speaker: str
    text: str
    emotion: str = ""
    tone: str = ""
    volume: str = ""
    timing: str = ""


@dataclass
class ActionDetail:
    character: str
    action_name: str
    description: str
    start_pose: str = ""
    end_pose: str = ""
    speed: str = ""
    equipment_used: List[str] = field(default_factory=list)
    skill_used: str = ""


@dataclass
class ShotInfo:
    shot_number: int
    duration: float
    scene_profile_id: str = ""
    scene_profile_version: int = 1
    character_profile_ids: List[str] = field(default_factory=list)
    character_profile_versions: Dict[str, int] = field(default_factory=dict)
    prompt_focus: str = ""
    shot_type: str = ""
    camera_angle: str = ""
    camera_movement: str = ""
    description: str = ""
    environment: str = ""
    lighting: str = ""
    characters_in_shot: List[str] = field(default_factory=list)
    actions: List[ActionDetail] = field(default_factory=list)
    dialogues: List[DialogueLine] = field(default_factory=list)
    sound_effects: List[str] = field(default_factory=list)
    music: str = ""


@dataclass
class SceneInfo:
    scene_number: int
    scene_profile_id: str = ""
    scene_profile_version: int = 1
    scene_type: str = ""
    title: str = ""
    description: str = ""
    story_function: str = ""
    location: str = ""
    location_detail: str = ""
    time: str = ""
    weather: str = ""
    lighting: str = ""
    atmosphere: str = ""
    mood: str = ""
    llm_summary: str = ""
    must_have: List[str] = field(default_factory=list)
    forbidden: List[str] = field(default_factory=list)
    shots: List[ShotInfo] = field(default_factory=list)


@dataclass
class FullScript:
    title: str = ""
    synopsis: str = ""
    total_duration: float = 0.0
    tone: str = ""
    themes: List[str] = field(default_factory=list)
    characters: List[CharacterInfo] = field(default_factory=list)
    scenes: List[SceneInfo] = field(default_factory=list)
    active_character_profiles: List[Dict[str, Any]] = field(default_factory=list)
    library_character_profiles: List[Dict[str, Any]] = field(default_factory=list)
    temporary_character_profiles: List[Dict[str, Any]] = field(default_factory=list)
    matched_character_profiles: List[Dict[str, Any]] = field(default_factory=list)
    matched_scene_profiles: List[Dict[str, Any]] = field(default_factory=list)
    character_resolution: Dict[str, Any] = field(default_factory=dict)
    generation_intent: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "synopsis": self.synopsis,
            "total_duration": self.total_duration,
            "tone": self.tone,
            "themes": self.themes,
            "characters": [
                {
                    "name": c.name,
                    "profile_id": c.profile_id,
                    "profile_version": c.profile_version,
                    "role_type": c.role_type,
                    "archetype": c.archetype,
                    "appearance": c.appearance,
                    "personality": c.personality,
                    "current_emotion": c.current_emotion,
                    "facial_expression": c.facial_expression,
                }
                for c in self.characters
            ],
            "scenes": [
                {
                    "scene_number": s.scene_number,
                    "scene_profile_id": s.scene_profile_id,
                    "scene_profile_version": s.scene_profile_version,
                    "scene_type": s.scene_type,
                    "title": s.title,
                    "description": s.description,
                    "location": s.location,
                    "shots_count": len(s.shots),
                }
                for s in self.scenes
            ],
            "active_character_profiles": self.active_character_profiles,
            "library_character_profiles": self.library_character_profiles,
            "temporary_character_profiles": self.temporary_character_profiles,
            "matched_character_profiles": self.matched_character_profiles,
            "matched_scene_profiles": self.matched_scene_profiles,
            "character_resolution": self.character_resolution,
            "generation_intent": self.generation_intent,
        }


class ScriptGenerator:
    def __init__(self) -> None:
        self.llm = DoubaoLLM()

    async def prepare_character_resolution(
        self,
        *,
        user_input: str,
        style: str = "",
        target_total_duration: Optional[float] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        normalized_characters = [self._normalize_character_profile(item) for item in (character_profiles or [])]
        intent = await self._extract_generation_intent(
            user_input=user_input,
            style=style,
            target_total_duration=target_total_duration,
        )
        matched_characters = await self._select_character_profiles(
            user_input=user_input,
            intent=intent,
            profiles=normalized_characters,
        )
        temporary_characters: List[Dict[str, Any]] = []
        unmatched_character_queries = self._identify_unmatched_character_queries(
            user_input=user_input,
            intent=intent,
            matched_characters=matched_characters,
        )
        character_resolution = {
            "status": "matched" if matched_characters else "none",
            "message": "已匹配到角色档案" if matched_characters else "未匹配到角色档案",
            "needs_user_action": False,
        }
        if unmatched_character_queries:
            temporary_characters = await self._generate_temporary_character_profiles(
                user_input=user_input,
                style=style,
                intent={**intent, "character_queries": unmatched_character_queries},
                desired_count=max(1, len(unmatched_character_queries)),
            )
            if temporary_characters:
                if matched_characters:
                    character_resolution = {
                        "status": "partially_matched",
                        "message": (
                            f"已匹配 {len(matched_characters)} 个正式角色，"
                            f"并为剩余 {len(temporary_characters)} 个未命中角色自动生成临时角色草稿"
                        ),
                        "needs_user_action": False,
                    }
                else:
                    character_resolution = {
                        "status": "temporary_generated",
                        "message": "未匹配到正式角色档案，已自动生成临时角色草稿",
                        "needs_user_action": False,
                    }
        elif not matched_characters:
            character_resolution = {
                "status": "needs_user_action",
                "message": "当前输入没有形成明确角色模板，建议先选择已有角色或新建角色档案",
                "needs_user_action": True,
            }

        return {
            "generation_intent": intent,
            "library_character_profiles": matched_characters,
            "temporary_character_profiles": temporary_characters,
            "active_character_profiles": [*matched_characters, *temporary_characters],
            "character_resolution": character_resolution,
            "selected_character_ids": [item.get("id") for item in matched_characters if item.get("id")],
        }

    async def generate_full_script(
        self,
        user_input: str,
        *,
        style: str = "",
        target_total_duration: Optional[float] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        scene_profiles: Optional[List[Dict[str, Any]]] = None,
        reference_images: Optional[List[Dict[str, Any]]] = None,
        generation_intent: Optional[Dict[str, Any]] = None,
        character_resolution: Optional[Dict[str, Any]] = None,
        library_character_profiles: Optional[List[Dict[str, Any]]] = None,
        temporary_character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> FullScript:
        logger.info("开始生成约束型剧本: %s", user_input[:120])

        normalized_scenes = [self._normalize_scene_profile(item) for item in (scene_profiles or [])]
        normalized_characters = [self._normalize_character_profile(item) for item in (character_profiles or [])]
        normalized_library_characters = [
            self._normalize_character_profile(item) for item in (library_character_profiles or [])
        ]
        normalized_temporary_characters = [
            self._normalize_character_profile(item) for item in (temporary_character_profiles or [])
        ]

        if generation_intent:
            intent = dict(generation_intent or {})
            matched_characters = normalized_library_characters
            temporary_characters = normalized_temporary_characters
            character_resolution = dict(character_resolution or {})
            if not matched_characters and not temporary_characters:
                matched_characters = normalized_characters
            logger.info(
                "复用已确认角色结果，跳过角色识别模型: library=%s temporary=%s",
                len(matched_characters),
                len(temporary_characters),
            )
        else:
            character_resolution_result = await self.prepare_character_resolution(
                user_input=user_input,
                style=style,
                target_total_duration=target_total_duration,
                character_profiles=character_profiles,
            )
            intent = character_resolution_result["generation_intent"]
            matched_characters = character_resolution_result["library_character_profiles"]
            temporary_characters = character_resolution_result["temporary_character_profiles"]
            character_resolution = character_resolution_result["character_resolution"]
        matched_scenes = await self._select_scene_profiles(
            user_input=user_input,
            intent=intent,
            profiles=normalized_scenes,
        )
        active_characters = [*matched_characters, *temporary_characters]

        script_data = await self._call_llm_for_script(
            user_input=user_input,
            style=style,
            target_total_duration=target_total_duration,
            reference_image_count=len(reference_images or []),
            intent=intent,
            matched_characters=active_characters,
            matched_scenes=matched_scenes,
        )

        try:
            full_script = self._parse_script_data(
                data=script_data,
                original_input=user_input,
                matched_characters=active_characters,
                matched_scenes=matched_scenes,
                intent=intent,
                library_characters=matched_characters,
                temporary_characters=temporary_characters,
                character_resolution=character_resolution,
            )
            self._validate_full_script(full_script)
        except ValueError as exc:
            if not self._should_retry_for_script_structure_error(exc):
                raise
            logger.warning("剧本结构不完整，准备重试一次: %s", exc)
            retry_data = await self._call_llm_for_script(
                user_input=user_input,
                style=style,
                target_total_duration=target_total_duration,
                reference_image_count=len(reference_images or []),
                intent=intent,
                matched_characters=active_characters,
                matched_scenes=matched_scenes,
                correction_note=(
                    f"上一次生成结果存在结构问题：{exc}。"
                    " 请重新输出完整剧本，必须包含非空标题、至少 1 个场景，且每个场景至少 1 个镜头。"
                    " scenes 不能为空，scene.shots 不能为空。"
                ),
            )
            full_script = self._parse_script_data(
                data=retry_data,
                original_input=user_input,
                matched_characters=active_characters,
                matched_scenes=matched_scenes,
                intent=intent,
                library_characters=matched_characters,
                temporary_characters=temporary_characters,
                character_resolution=character_resolution,
            )
            self._validate_full_script(full_script)
        full_script = await self._align_script_duration(
            full_script,
            user_input=user_input,
            style=style,
            target_total_duration=target_total_duration,
            reference_image_count=len(reference_images or []),
            intent=intent,
            matched_characters=active_characters,
            matched_scenes=matched_scenes,
        )
        full_script = await self._repair_shot_late_entry_risks(
            full_script,
            user_input=user_input,
            style=style,
            target_total_duration=target_total_duration,
            reference_image_count=len(reference_images or []),
            intent=intent,
            matched_characters=active_characters,
            matched_scenes=matched_scenes,
        )
        logger.info("剧本生成完成: %s", full_script.title)
        return full_script

    async def _extract_generation_intent(
        self,
        *,
        user_input: str,
        style: str,
        target_total_duration: Optional[float],
    ) -> Dict[str, Any]:
        system_prompt = """你是视频创作需求分析器。请从用户输入中抽取生成意图，不要创作剧本。

输出必须是合法 JSON：
{
  "character_queries": [
    {
      "name_hint": "",
      "category": "",
      "role": "",
      "archetype": "",
      "keywords": ["", ""]
    }
  ],
  "scene_queries": [
    {
      "name_hint": "",
      "category": "",
      "scene_type": "",
      "story_function": "",
      "keywords": ["", ""]
    }
  ],
  "style_keywords": ["", ""],
  "tone_keywords": ["", ""],
  "duration_preference": 50.0
}

规则：
1. 只抽取用户真正表达的需求，不脑补具体剧情
2. 如果用户明确列出了角色名单、角色表、代号、本名或群像角色，必须完整抽取，不要擅自省略
3. 如果用户没有明确指定角色或场景数量，给出合理的 1-3 个查询意图
4. JSON key 和字符串值都必须使用双引号
5. 不要输出 markdown 代码块或解释文字"""
        user_prompt = f"用户输入：{user_input}\n视觉风格：{style or '未指定'}\n目标时长：{target_total_duration or '未指定'}"
        try:
            response = await self.llm.chat_completion(
                [
                    DoubaoMessage(role="system", content=system_prompt),
                    DoubaoMessage(role="user", content=user_prompt),
                ],
                temperature=0.2,
                max_tokens=1400,
            )
            payload = self._parse_llm_json(response.get_content().strip())
            llm_character_queries = payload.get("character_queries") or []
            logger.info(
                "角色识别结果 | llm=%s",
                json.dumps(llm_character_queries, ensure_ascii=False),
            )
            return {
                "character_queries": llm_character_queries,
                "scene_queries": payload.get("scene_queries") or [],
                "style_keywords": payload.get("style_keywords") or self._tokenize(style),
                "tone_keywords": payload.get("tone_keywords") or [],
                "duration_preference": self._safe_float(
                    payload.get("duration_preference", target_total_duration or 0),
                    default=float(target_total_duration or 0),
                ),
            }
        except MissingProviderConfigError:
            raise
        except Exception as exc:
            logger.error("生成意图提取失败，终止自动角色分析: %s", exc, exc_info=True)
            raise RuntimeError("角色分析调用豆包失败，请检查临时 Key 或服务配置后重试。") from exc

    async def _select_character_profiles(
        self,
        *,
        user_input: str,
        intent: Dict[str, Any],
        profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        desired_count = self._estimate_desired_character_count(intent)
        return await self._select_profiles(
            profile_type="character",
            user_input=user_input,
            intent_queries=intent.get("character_queries") or [],
            profiles=profiles,
            desired_count=desired_count,
        )

    async def _select_scene_profiles(
        self,
        *,
        user_input: str,
        intent: Dict[str, Any],
        profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return await self._select_profiles(
            profile_type="scene",
            user_input=user_input,
            intent_queries=intent.get("scene_queries") or [],
            profiles=profiles,
            desired_count=3,
        )

    def _estimate_desired_character_count(self, intent: Dict[str, Any]) -> int:
        queries = [query for query in (intent.get("character_queries") or []) if self._query_has_meaning(query)]
        if not queries:
            return 1
        return max(1, len(queries))

    def _identify_unmatched_character_queries(
        self,
        *,
        user_input: str,
        intent: Dict[str, Any],
        matched_characters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        meaningful_queries = [
            query
            for query in (intent.get("character_queries") or [])
            if self._query_has_meaning(query)
        ]
        if not meaningful_queries:
            return []
        if not matched_characters:
            return meaningful_queries

        unmatched: List[Dict[str, Any]] = []
        for query in meaningful_queries:
            if any(
                self._query_matches_character_profile(
                    query=query,
                    profile=profile,
                    user_input=user_input,
                )
                for profile in matched_characters
            ):
                continue
            unmatched.append(query)
        return unmatched

    def _query_matches_character_profile(
        self,
        *,
        query: Dict[str, Any],
        profile: Dict[str, Any],
        user_input: str,
    ) -> bool:
        normalized_haystack_parts = [
            str(profile.get("name") or "").strip().lower(),
            str(profile.get("category") or "").strip().lower(),
            str(profile.get("role") or "").strip().lower(),
            str(profile.get("archetype") or "").strip().lower(),
            str(profile.get("description") or "").strip().lower(),
            str(profile.get("llm_summary") or "").strip().lower(),
        ]
        normalized_haystack_parts.extend(str(item).strip().lower() for item in (profile.get("aliases") or []) if str(item).strip())
        normalized_haystack = " ".join(part for part in normalized_haystack_parts if part)
        if not normalized_haystack:
            return False

        for key in ["name_hint", "role", "archetype", "category"]:
            normalized_value = str(query.get(key) or "").strip().lower()
            if normalized_value and normalized_value in normalized_haystack:
                return True

        keywords = [str(item).strip().lower() for item in (query.get("keywords") or []) if str(item).strip()]
        if keywords and any(keyword in normalized_haystack for keyword in keywords):
            return True

        return self._score_profile(
            profile_type="character",
            profile=profile,
            query=query,
            user_input=user_input,
        ) >= 2.5

    def _has_meaningful_character_intent(self, intent: Dict[str, Any]) -> bool:
        return any(self._query_has_meaning(query) for query in (intent.get("character_queries") or []))

    def _query_has_meaning(self, query: Dict[str, Any]) -> bool:
        if not isinstance(query, dict):
            return False
        for key in ["name_hint", "category", "role", "archetype", "scene_type", "story_function"]:
            if str(query.get(key) or "").strip():
                return True
        return any(str(item).strip() for item in (query.get("keywords") or []))

    async def _generate_temporary_character_profiles(
        self,
        *,
        user_input: str,
        style: str,
        intent: Dict[str, Any],
        desired_count: int,
    ) -> List[Dict[str, Any]]:
        system_prompt = """你是角色设定设计师。请基于用户输入和角色意图，生成可直接用于后续剧本/图片/视频生成的临时角色档案草稿。

输出必须是合法 JSON：
{
  "characters": [
    {
      "name": "",
      "category": "",
      "role": "",
      "archetype": "",
      "age_range": "",
      "gender_presentation": "",
      "description": "",
      "appearance": "",
      "personality": "",
      "core_appearance": "",
      "hair": "",
      "face_features": "",
      "body_shape": "",
      "outfit": "",
      "gear": "",
      "color_palette": "",
      "visual_do_not_change": "",
      "speaking_style": "",
      "common_actions": "",
      "emotion_baseline": "",
      "voice_description": "",
      "forbidden_behaviors": "",
      "llm_summary": "",
      "image_prompt_base": "",
      "video_prompt_base": "",
      "negative_prompt": "",
      "tags": ["", ""],
      "must_keep": ["", ""],
      "forbidden_traits": ["", ""],
      "aliases": ["", ""]
    }
  ]
}

规则：
1. 这是临时角色草稿，不要虚构复杂世界观背景
2. 要优先保证外观稳定性、说话方式和行为约束清晰
3. llm_summary 控制在 100-250 字以内
4. image_prompt_base 聚焦静态外观
5. video_prompt_base 聚焦动态表演和动作
6. 只输出 JSON"""
        user_prompt = json.dumps(
            {
                "user_input": user_input,
                "style": style,
                "character_queries": intent.get("character_queries") or [],
                "desired_count": desired_count,
            },
            ensure_ascii=False,
        )
        try:
            response = await self.llm.chat_completion(
                [
                    DoubaoMessage(role="system", content=system_prompt),
                    DoubaoMessage(role="user", content=user_prompt),
                ],
                temperature=0.35,
                max_tokens=2400,
            )
            payload = self._parse_llm_json(response.get_content().strip())
            drafts = []
            for index, item in enumerate((payload.get("characters") or [])[:desired_count], start=1):
                normalized = self._normalize_character_profile(item)
                normalized["id"] = normalized.get("id") or f"temp_char_{index}_{abs(hash((user_input, normalized.get('name', ''), index))) % 10**10}"
                normalized["source"] = "ai-generated-draft"
                normalized["profile_version"] = 1
                drafts.append(normalized)
            return drafts
        except MissingProviderConfigError:
            raise
        except Exception as exc:
            logger.warning("临时角色草稿生成失败: %s", exc)
            return []

    async def _select_profiles(
        self,
        *,
        profile_type: str,
        user_input: str,
        intent_queries: List[Dict[str, Any]],
        profiles: List[Dict[str, Any]],
        desired_count: int,
    ) -> List[Dict[str, Any]]:
        if not profiles:
            return []

        queries = intent_queries or [{}]
        scored: List[tuple[float, Dict[str, Any]]] = []
        for profile in profiles:
            score = 0.0
            for query in queries:
                score = max(score, self._score_profile(profile_type=profile_type, profile=profile, query=query, user_input=user_input))
            scored.append((score, profile))

        scored.sort(key=lambda item: item[0], reverse=True)
        shortlist_limit = max(6, desired_count * 2)
        shortlisted = [profile for score, profile in scored if score > 0][:shortlist_limit]
        if not shortlisted:
            return []

        llm_selected = await self._choose_profiles_with_llm(
            profile_type=profile_type,
            user_input=user_input,
            intent_queries=queries,
            candidates=shortlisted,
            desired_count=desired_count,
        )
        return llm_selected or shortlisted[:desired_count]

    async def _choose_profiles_with_llm(
        self,
        *,
        profile_type: str,
        user_input: str,
        intent_queries: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        desired_count: int,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []
        if len(candidates) <= desired_count:
            return candidates

        system_prompt = """你是档案匹配器。你的任务是从候选档案中选出最适合本次生成任务的档案。

输出必须是合法 JSON：
{
  "selected_ids": ["id1", "id2"]
}

规则：
1. 只能从候选列表中选
2. 优先选择最贴合用户意图且约束清晰的档案
3. 不要解释，不要输出 markdown"""
        compact_candidates = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "role": item.get("role"),
                "archetype": item.get("archetype"),
                "scene_type": item.get("scene_type"),
                "story_function": item.get("story_function"),
                "llm_summary": item.get("llm_summary"),
                "tags": item.get("tags"),
            }
            for item in candidates
        ]
        try:
            response = await self.llm.chat_completion(
                [
                    DoubaoMessage(role="system", content=system_prompt),
                    DoubaoMessage(
                        role="user",
                        content=(
                            f"类型：{profile_type}\n"
                            f"用户输入：{user_input}\n"
                            f"意图：{json.dumps(intent_queries, ensure_ascii=False)}\n"
                            f"候选档案：{json.dumps(compact_candidates, ensure_ascii=False)}\n"
                            f"请返回最多 {desired_count} 个最合适的 selected_ids。"
                        ),
                    ),
                ],
                temperature=0.15,
                max_tokens=800,
            )
            payload = self._parse_llm_json(response.get_content().strip())
            selected_ids = [str(item).strip() for item in (payload.get("selected_ids") or []) if str(item).strip()]
            lookup = {item.get("id"): item for item in candidates if item.get("id")}
            selected = [lookup[item_id] for item_id in selected_ids if item_id in lookup]
            return selected[:desired_count]
        except MissingProviderConfigError:
            raise
        except Exception as exc:
            logger.warning("%s 档案二次筛选失败，回退评分结果: %s", profile_type, exc)
            return []

    async def _call_llm_for_script(
        self,
        *,
        user_input: str,
        style: str,
        target_total_duration: Optional[float],
        reference_image_count: int,
        intent: Dict[str, Any],
        matched_characters: List[Dict[str, Any]],
        matched_scenes: List[Dict[str, Any]],
        correction_note: str = "",
    ) -> Dict[str, Any]:
        character_cards = [self._build_character_constraint_card(item) for item in matched_characters]
        scene_cards = [self._build_scene_constraint_card(item) for item in matched_scenes]
        input_policy = self._build_script_input_policy(user_input)
        correction_note = self._merge_correction_note_with_input_fidelity(
            correction_note,
            user_input=user_input,
        )
        system_prompt = """你是一位顶级短视频编剧，但你的创作必须严格服从给定档案约束。

【工作方式】
1. 先理解用户需求
2. 只能在 selected_characters 和 selected_scenes 的约束范围内创作
3. 新增细节不得违背 must_keep / must_have / forbidden
4. 每个角色、每个场景都必须尽量绑定档案 ID 和版本
5. 剧本阶段没有角色图片可用，角色恒定身份只能依赖 selected_characters 里的 llm_summary / must_keep / forbidden / speaking_style / voice_description / common_actions

【用户输入保真】
1. user_input 是剧情事实的第一来源，必须优先保留其中明确写出的角色关系、事件顺序、时间地点、冲突目标和结局
2. 如果 user_input 已经很详细，默认执行“保守改写”：只把现有内容整理成可拍摄镜头与必要衔接，不新增支线、反转、前史、世界观补充、额外角色或额外场景
3. 用户没有明确写出的心理动机、背景说明、象征隐喻、额外设定，宁可留白，也不要自行脑补
4. correction_note 只允许修正结构、时长或镜头问题，不代表可以借机改写剧情主线
5. 当 selected_characters / selected_scenes 与 user_input 同时存在时，剧情事实以 user_input 为准，角色命名和稳定外观约束以档案为准

【输出要求】
1. 输出必须是合法 JSON
2. 绝不能输出 markdown 代码块、注释、解释文字
2.1 只能输出一个完整的 JSON 对象，首字符必须是 {，末字符必须是 }
2.2 宁可压缩措辞、减少冗余描述，也不能输出被截断的半截 JSON
2.3 所有字符串中的双引号必须正确转义，禁止输出未闭合字符串
3. 每个场景必须输出 scene_profile_id 和 scene_profile_version
4. 每个镜头必须输出 scene_profile_id / scene_profile_version / character_profile_ids / character_profile_versions / prompt_focus
5. characters 中每个角色必须输出 character_profile_id 和 profile_version
6. 镜头数量必须按内容自适应，不许模板化凑镜头
7. 如果给定目标总时长，所有 shots.duration 总和必须尽量贴近目标，总误差不能超过目标时长 10% 和 3 秒中的更小值
8. 只要角色绑定了 selected_characters 中的 character_profile_id，就必须严格使用该档案原始 name，不允许改名、起别称、写错同音名
9. 单个镜头默认只写首帧已经在画面中的角色及其动作、对白、互动，不要把“新角色中途走入/闯入/突然出现”写在同一镜头里
10. 如果剧情需要新角色加入，必须从一个新镜头开始，并在该新镜头的 character_profile_ids / characters_in_shot 中明确包含该角色
11. 尽量避免在同一镜头描述角色先不在场、后入场；角色登场要通过切新镜头解决，而不是在镜头中途补进来
12. scenes 数组至少包含 1 个场景，禁止输出空数组
13. 每个 scene.shots 数组至少包含 1 个镜头，禁止输出空数组
14. title 必须是非空字符串，不能留空
15. 当 input_policy.fidelity_mode = "strict" 时，剧情改写幅度必须最小化；优先复用用户原始表述，不要擅自换剧情重心

【JSON 结构】
{
  "title": "",
  "synopsis": "",
  "tone": "",
  "themes": ["", ""],
  "characters": [
    {
      "name": "",
      "character_profile_id": "",
      "profile_version": 1,
      "category": "",
      "role_type": "",
      "archetype": "",
      "appearance": "",
      "personality": "",
      "current_emotion": "",
      "facial_expression": "",
      "body_language": "",
      "current_pose": "",
      "speaking_style": "",
      "common_actions": "",
      "equipment": ["", ""],
      "skills": ["", ""]
    }
  ],
  "scenes": [
    {
      "scene_number": 1,
      "scene_profile_id": "",
      "scene_profile_version": 1,
      "scene_type": "",
      "title": "",
      "description": "",
      "story_function": "",
      "location": "",
      "location_detail": "",
      "time": "",
      "weather": "",
      "lighting": "",
      "atmosphere": "",
      "mood": "",
      "shots": [
        {
          "shot_number": 1,
          "duration": 3.5,
          "scene_profile_id": "",
          "scene_profile_version": 1,
          "character_profile_ids": ["", ""],
          "character_profile_versions": {"id": 1},
          "prompt_focus": "",
          "shot_type": "",
          "camera_angle": "",
          "camera_movement": "",
          "description": "",
          "environment": "",
          "lighting": "",
          "characters_in_shot": ["", ""],
          "actions": [
            {
              "character": "",
              "action_name": "",
              "description": "",
              "start_pose": "",
              "end_pose": "",
              "speed": "",
              "equipment_used": [""],
              "skill_used": ""
            }
          ],
          "dialogues": [
            {
              "speaker": "",
              "text": "",
              "emotion": "",
              "tone": "",
              "volume": "",
              "timing": ""
            }
          ],
          "sound_effects": ["", ""],
          "music": ""
        }
      ]
    }
  ]
}"""

        user_payload = {
            "user_input": user_input,
            "style": style,
            "reference_image_count": reference_image_count,
            "intent": intent,
            "input_policy": {
                "fidelity_mode": input_policy["fidelity_mode"],
                "is_user_input_detailed": input_policy["is_user_input_detailed"],
                "expansion_scope": input_policy["expansion_scope"],
                "preserve_points": input_policy["preserve_points"],
            },
            "selected_characters": character_cards,
            "selected_scenes": scene_cards,
            "target_total_duration": float(target_total_duration) if target_total_duration is not None else None,
            "correction_note": correction_note,
        }
        request_messages = [
            DoubaoMessage(role="system", content=system_prompt),
            DoubaoMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
        ]
        response = await self.llm.chat_completion(
            request_messages,
            temperature=float(input_policy["temperature"]),
            max_tokens=20000,
            timeout=httpx.Timeout(
                connect=float(getattr(settings, "DOUBAO_CONNECT_TIMEOUT", 20.0)),
                read=float(getattr(settings, "DOUBAO_SCRIPT_READ_TIMEOUT", 360.0)),
                write=float(getattr(settings, "DOUBAO_WRITE_TIMEOUT", 60.0)),
                pool=float(getattr(settings, "DOUBAO_POOL_TIMEOUT", 60.0)),
            ),
            max_retries=max(1, int(getattr(settings, "DOUBAO_MAX_RETRIES", 2))),
            request_label="generate_full_script",
        )
        content = response.get_content().strip()
        if not content:
            raise ValueError("豆包返回内容为空")
        try:
            return self._parse_llm_json(content)
        except ValueError as exc:
            logger.warning("generate_full_script returned invalid JSON, retrying once: %s", exc)
            repair_messages = [
                DoubaoMessage(
                    role="system",
                    content=(
                        "你是 JSON 修正器。请基于同一任务重新输出一个完整、合法、可解析的 JSON 对象。"
                        "禁止输出解释、禁止 markdown、禁止代码块。"
                        "输出必须只包含一个 JSON 对象，首字符是 {，末字符是 }。"
                    ),
                ),
                DoubaoMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
                DoubaoMessage(
                    role="assistant",
                    content=content,
                ),
                DoubaoMessage(
                    role="user",
                    content=(
                        "你上一次返回的内容不是合法 JSON。"
                        "请保留原任务语义，重新输出完整 JSON。"
                        "如果内容太长，请缩短描述文本，但必须保留字段结构完整。"
                    ),
                ),
            ]
            repair_response = await self.llm.chat_completion(
                repair_messages,
                temperature=0.05,
                max_tokens=5600,
                timeout=httpx.Timeout(
                    connect=float(getattr(settings, "DOUBAO_CONNECT_TIMEOUT", 20.0)),
                    read=float(getattr(settings, "DOUBAO_SCRIPT_READ_TIMEOUT", 360.0)),
                    write=float(getattr(settings, "DOUBAO_WRITE_TIMEOUT", 60.0)),
                    pool=float(getattr(settings, "DOUBAO_POOL_TIMEOUT", 60.0)),
                ),
                max_retries=max(1, int(getattr(settings, "DOUBAO_MAX_RETRIES", 2))),
                request_label="generate_full_script_repair_json",
            )
            repaired_content = repair_response.get_content().strip()
            if not repaired_content:
                raise ValueError("豆包 JSON 修正返回内容为空") from exc
            return self._parse_llm_json(repaired_content)

    def _should_retry_for_script_structure_error(self, exc: Exception) -> bool:
        if not isinstance(exc, ValueError):
            return False
        return str(exc) in {
            "生成结果缺少标题",
            "生成结果缺少场景",
            "生成结果缺少分镜",
        }

    async def _align_script_duration(
        self,
        full_script: FullScript,
        *,
        user_input: str,
        style: str,
        target_total_duration: Optional[float],
        reference_image_count: int,
        intent: Dict[str, Any],
        matched_characters: List[Dict[str, Any]],
        matched_scenes: List[Dict[str, Any]],
    ) -> FullScript:
        if target_total_duration is None:
            return full_script

        tolerance = self._duration_tolerance(target_total_duration)
        current_duration = full_script.total_duration
        if self._duration_within_tolerance(current_duration, target_total_duration, tolerance):
            return full_script

        correction_note = (
            f"上一次生成总时长为 {current_duration:.1f} 秒，目标是 {target_total_duration:.1f} 秒。"
            " 请保持角色和场景绑定不变，增加或压缩有效镜头，使总时长严格贴近目标。"
            " 同时继续遵守新角色必须从新镜头开始出场，不要写成同一镜头中途入场。"
        )
        retry_data = await self._call_llm_for_script(
            user_input=user_input,
            style=style,
            target_total_duration=target_total_duration,
            reference_image_count=reference_image_count,
            intent=intent,
            matched_characters=matched_characters,
            matched_scenes=matched_scenes,
            correction_note=correction_note,
        )
        retried_script = self._parse_script_data(
            data=retry_data,
            original_input=user_input,
            matched_characters=matched_characters,
            matched_scenes=matched_scenes,
            intent=intent,
        )
        self._validate_full_script(retried_script)

        retry_duration = retried_script.total_duration
        if abs(retry_duration - target_total_duration) < abs(current_duration - target_total_duration):
            full_script = retried_script
            current_duration = retry_duration

        if not self._duration_within_tolerance(current_duration, target_total_duration, tolerance):
            self._rebalance_script_duration(full_script, target_total_duration)
        return full_script

    async def _repair_shot_late_entry_risks(
        self,
        full_script: FullScript,
        *,
        user_input: str,
        style: str,
        target_total_duration: Optional[float],
        reference_image_count: int,
        intent: Dict[str, Any],
        matched_characters: List[Dict[str, Any]],
        matched_scenes: List[Dict[str, Any]],
    ) -> FullScript:
        current_risks = self._collect_shot_late_entry_risks(full_script)
        if not current_risks:
            return full_script

        correction_note = (
            "上一次生成的剧本中，以下镜头疑似把新角色写成同一镜头中途入场："
            + "；".join(current_risks[:8])
            + "。请保持剧情主线、角色绑定、场景绑定和整体风格不变，"
            + "把这些角色入场改写为从新镜头开始，不要在同一镜头里写“突然出现/走入/闯入/进入画面”之类的中途入场。"
        )

        try:
            retry_data = await self._call_llm_for_script(
                user_input=user_input,
                style=style,
                target_total_duration=target_total_duration,
                reference_image_count=reference_image_count,
                intent=intent,
                matched_characters=matched_characters,
                matched_scenes=matched_scenes,
                correction_note=correction_note,
            )
            retried_script = self._parse_script_data(
                data=retry_data,
                original_input=user_input,
                matched_characters=matched_characters,
                matched_scenes=matched_scenes,
                intent=intent,
            )
            self._validate_full_script(retried_script)
        except Exception as exc:
            logger.warning("剧本镜头入场稳定性二次修正失败，保留原结果: %s", exc)
            return full_script

        retried_risks = self._collect_shot_late_entry_risks(retried_script)
        if len(retried_risks) >= len(current_risks):
            logger.warning(
                "剧本镜头入场稳定性二次修正未改善，保留原结果。风险数: %s -> %s",
                len(current_risks),
                len(retried_risks),
            )
            return full_script

        if target_total_duration is not None:
            tolerance = self._duration_tolerance(target_total_duration)
            if not self._duration_within_tolerance(retried_script.total_duration, target_total_duration, tolerance):
                self._rebalance_script_duration(retried_script, target_total_duration)

        logger.info(
            "剧本镜头入场稳定性二次修正完成，风险数: %s -> %s",
            len(current_risks),
            len(retried_risks),
        )
        return retried_script

    def _parse_script_data(
        self,
        *,
        data: Dict[str, Any],
        original_input: str,
        matched_characters: List[Dict[str, Any]],
        matched_scenes: List[Dict[str, Any]],
        intent: Dict[str, Any],
        library_characters: Optional[List[Dict[str, Any]]] = None,
        temporary_characters: Optional[List[Dict[str, Any]]] = None,
        character_resolution: Optional[Dict[str, Any]] = None,
    ) -> FullScript:
        character_lookup = {item.get("id"): item for item in matched_characters if item.get("id")}
        character_name_lookup = {
            self._normalize_name(item.get("name")): item for item in matched_characters if item.get("name")
        }
        scene_lookup = {item.get("id"): item for item in matched_scenes if item.get("id")}
        scene_name_lookup = {
            self._normalize_name(item.get("name")): item for item in matched_scenes if item.get("name")
        }

        characters: List[CharacterInfo] = []
        output_name_to_profile_id: Dict[str, str] = {}
        profile_id_to_canonical_name: Dict[str, str] = {}
        for char_data in data.get("characters", []):
            matched_profile = self._match_character_from_output(char_data, character_lookup, character_name_lookup)
            profile_id = str(char_data.get("character_profile_id") or matched_profile.get("id") or "").strip()
            profile_version = self._safe_int(
                char_data.get("profile_version", matched_profile.get("profile_version", 1)),
                default=matched_profile.get("profile_version", 1) or 1,
            )
            canonical_name = str(matched_profile.get("name") or char_data.get("name") or "").strip()
            raw_output_name = str(char_data.get("name") or "").strip()
            if profile_id:
                if canonical_name:
                    profile_id_to_canonical_name[profile_id] = canonical_name
                    output_name_to_profile_id[self._normalize_name(canonical_name)] = profile_id
                if raw_output_name:
                    output_name_to_profile_id[self._normalize_name(raw_output_name)] = profile_id
            characters.append(
                CharacterInfo(
                    name=canonical_name,
                    profile_id=profile_id,
                    profile_version=profile_version,
                    category=str(char_data.get("category") or matched_profile.get("category") or ""),
                    role_type=str(char_data.get("role_type") or matched_profile.get("role") or ""),
                    archetype=str(char_data.get("archetype") or matched_profile.get("archetype") or ""),
                    appearance=str(char_data.get("appearance") or matched_profile.get("image_prompt_base") or matched_profile.get("appearance") or ""),
                    personality=str(char_data.get("personality") or matched_profile.get("personality") or ""),
                    current_emotion=str(char_data.get("current_emotion") or ""),
                    facial_expression=str(char_data.get("facial_expression") or ""),
                    body_language=str(char_data.get("body_language") or ""),
                    current_pose=str(char_data.get("current_pose") or ""),
                    speaking_style=str(char_data.get("speaking_style") or matched_profile.get("speaking_style") or ""),
                    common_actions=str(char_data.get("common_actions") or matched_profile.get("common_actions") or ""),
                    llm_summary=str(matched_profile.get("llm_summary") or ""),
                    must_keep=self._normalize_list(char_data.get("must_keep") or matched_profile.get("must_keep") or []),
                    forbidden=self._normalize_list(char_data.get("forbidden") or matched_profile.get("forbidden_traits") or []),
                    equipment=self._normalize_list(char_data.get("equipment") or []),
                    skills=self._normalize_list(char_data.get("skills") or []),
                )
            )

        scenes: List[SceneInfo] = []
        total_duration = 0.0
        for scene_index, scene_data in enumerate(data.get("scenes", []), start=1):
            matched_scene = self._match_scene_from_output(scene_data, scene_lookup, scene_name_lookup)
            scene_profile_id = str(scene_data.get("scene_profile_id") or matched_scene.get("id") or "").strip()
            scene_profile_version = self._safe_int(
                scene_data.get("scene_profile_version", matched_scene.get("profile_version", 1)),
                default=matched_scene.get("profile_version", 1) or 1,
            )
            scene = SceneInfo(
                scene_number=self._safe_int(scene_data.get("scene_number"), default=scene_index),
                scene_profile_id=scene_profile_id,
                scene_profile_version=scene_profile_version,
                scene_type=str(scene_data.get("scene_type") or matched_scene.get("scene_type") or ""),
                title=str(scene_data.get("title") or matched_scene.get("name") or f"场景{scene_index}"),
                description=str(scene_data.get("description") or ""),
                story_function=str(scene_data.get("story_function") or matched_scene.get("story_function") or ""),
                location=str(scene_data.get("location") or matched_scene.get("location") or ""),
                location_detail=str(scene_data.get("location_detail") or ""),
                time=str(scene_data.get("time") or matched_scene.get("time_setting") or ""),
                weather=str(scene_data.get("weather") or matched_scene.get("weather") or ""),
                lighting=str(scene_data.get("lighting") or matched_scene.get("lighting") or ""),
                atmosphere=str(scene_data.get("atmosphere") or matched_scene.get("atmosphere") or ""),
                mood=str(scene_data.get("mood") or ""),
                llm_summary=str(matched_scene.get("llm_summary") or ""),
                must_have=self._normalize_list(scene_data.get("must_have") or matched_scene.get("must_have_elements") or matched_scene.get("props_must_have") or []),
                forbidden=self._normalize_list(scene_data.get("forbidden") or matched_scene.get("forbidden_elements") or matched_scene.get("props_forbidden") or []),
            )

            for shot_index, shot_data in enumerate(scene_data.get("shots", []), start=1):
                actions = [
                    ActionDetail(
                        character=str(item.get("character") or ""),
                        action_name=str(item.get("action_name") or ""),
                        description=str(item.get("description") or ""),
                        start_pose=str(item.get("start_pose") or ""),
                        end_pose=str(item.get("end_pose") or ""),
                        speed=str(item.get("speed") or ""),
                        equipment_used=self._normalize_list(item.get("equipment_used") or []),
                        skill_used=str(item.get("skill_used") or ""),
                    )
                    for item in (shot_data.get("actions") or [])
                ]
                dialogues = [
                    DialogueLine(
                        speaker=str(item.get("speaker") or ""),
                        text=str(item.get("text") or ""),
                        emotion=str(item.get("emotion") or ""),
                        tone=str(item.get("tone") or ""),
                        volume=str(item.get("volume") or ""),
                        timing=str(item.get("timing") or ""),
                    )
                    for item in (shot_data.get("dialogues") or [])
                ]
                character_profile_ids = self._normalize_list(shot_data.get("character_profile_ids") or [])
                if not character_profile_ids:
                    character_profile_ids = self._match_character_ids_from_shot(
                        shot_data=shot_data,
                        actions=actions,
                        dialogues=dialogues,
                        characters=characters,
                        output_name_to_profile_id=output_name_to_profile_id,
                    )
                character_profile_versions = self._normalize_profile_version_map(
                    shot_data.get("character_profile_versions") or {},
                    characters=characters,
                    character_profile_ids=character_profile_ids,
                )
                normalized_characters_in_shot = self._canonicalize_name_list(
                    self._normalize_list(shot_data.get("characters_in_shot") or []),
                    output_name_to_profile_id=output_name_to_profile_id,
                    profile_id_to_canonical_name=profile_id_to_canonical_name,
                )
                actions = self._canonicalize_actions(
                    actions,
                    output_name_to_profile_id=output_name_to_profile_id,
                    profile_id_to_canonical_name=profile_id_to_canonical_name,
                )
                dialogues = self._canonicalize_dialogues(
                    dialogues,
                    output_name_to_profile_id=output_name_to_profile_id,
                    profile_id_to_canonical_name=profile_id_to_canonical_name,
                )
                shot = ShotInfo(
                    shot_number=self._safe_int(shot_data.get("shot_number"), default=shot_index),
                    duration=self._safe_float(shot_data.get("duration"), default=5.0),
                    scene_profile_id=str(shot_data.get("scene_profile_id") or scene_profile_id),
                    scene_profile_version=self._safe_int(
                        shot_data.get("scene_profile_version"),
                        default=scene_profile_version,
                    ),
                    character_profile_ids=character_profile_ids,
                    character_profile_versions=character_profile_versions,
                    prompt_focus=str(shot_data.get("prompt_focus") or ""),
                    shot_type=str(shot_data.get("shot_type") or ""),
                    camera_angle=str(shot_data.get("camera_angle") or ""),
                    camera_movement=str(shot_data.get("camera_movement") or ""),
                    description=str(shot_data.get("description") or ""),
                    environment=str(shot_data.get("environment") or ""),
                    lighting=str(shot_data.get("lighting") or scene.lighting or ""),
                    characters_in_shot=normalized_characters_in_shot,
                    actions=actions,
                    dialogues=dialogues,
                    sound_effects=self._normalize_list(shot_data.get("sound_effects") or []),
                    music=str(shot_data.get("music") or ""),
                )
                scene.shots.append(shot)

            scene.shots = self._normalize_scene_shots(scene)
            total_duration += sum(shot.duration for shot in scene.shots)
            scenes.append(scene)

        return FullScript(
            title=str(data.get("title") or "未命名剧本"),
            synopsis=str(data.get("synopsis") or original_input),
            total_duration=round(total_duration, 1),
            tone=str(data.get("tone") or "紧张"),
            themes=self._normalize_list(data.get("themes") or []),
            characters=characters,
            scenes=scenes,
            active_character_profiles=matched_characters,
            library_character_profiles=list(library_characters or []),
            temporary_character_profiles=list(temporary_characters or []),
            matched_character_profiles=matched_characters,
            matched_scene_profiles=matched_scenes,
            character_resolution=dict(character_resolution or {}),
            generation_intent=intent,
        )

    def _build_character_constraint_card(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": profile.get("id", ""),
            "name": profile.get("name", ""),
            "profile_version": profile.get("profile_version", 1),
            "category": profile.get("category", ""),
            "role": profile.get("role", ""),
            "archetype": profile.get("archetype", ""),
            "llm_summary": profile.get("llm_summary") or self._truncate_text(
                "；".join(
                    part
                    for part in [
                        profile.get("description"),
                        profile.get("core_appearance"),
                        profile.get("personality"),
                        profile.get("speaking_style"),
                        profile.get("voice_description"),
                    ]
                    if part
                ),
                240,
            ),
            "core_appearance": str(profile.get("core_appearance") or "").strip(),
            "outfit": str(profile.get("outfit") or "").strip(),
            "color_palette": str(profile.get("color_palette") or "").strip(),
            "speaking_style": str(profile.get("speaking_style") or "").strip(),
            "voice_description": str(profile.get("voice_description") or "").strip(),
            "common_actions": str(profile.get("common_actions") or "").strip(),
            "must_keep": self._normalize_list(
                profile.get("must_keep")
                or [
                    profile.get("hair"),
                    profile.get("face_features"),
                    profile.get("outfit"),
                    profile.get("visual_do_not_change"),
                ]
            ),
            "forbidden": self._normalize_list(profile.get("forbidden_traits") or profile.get("forbidden_behaviors") or []),
            "script_stage_rule": "Use llm_summary + must_keep + forbidden + voice_description as the source of truth. Do not infer conflicting visual or vocal changes from free-form story text.",
        }

    def _build_script_input_policy(self, user_input: str) -> Dict[str, Any]:
        normalized_input = str(user_input or "").strip()
        if not normalized_input:
            return {
                "fidelity_mode": "standard",
                "is_user_input_detailed": False,
                "expansion_scope": "可以做少量必要补全，但不要改写核心设定",
                "preserve_points": [],
                "temperature": 0.2,
            }

        lines = [line.strip() for line in re.split(r"\r?\n+", normalized_input) if line.strip()]
        sentence_candidates = [
            sentence.strip()
            for sentence in re.split(r"[\n。！？!?；;]+", normalized_input)
            if sentence.strip()
        ]
        bullet_lines = [
            line
            for line in lines
            if re.match(r"^(?:[-*•]|\d+[.)、])\s*", line)
        ]
        constraint_keywords = (
            "必须",
            "不要",
            "不能",
            "保留",
            "设定",
            "关系",
            "场景",
            "地点",
            "时间",
            "结局",
            "对白",
            "镜头",
            "分镜",
            "角色",
            "服装",
            "道具",
        )
        constraint_hit_count = sum(1 for keyword in constraint_keywords if keyword in normalized_input)
        detail_score = 0
        if len(normalized_input) >= 120:
            detail_score += 2
        if len(lines) >= 4:
            detail_score += 1
        if len(sentence_candidates) >= 4:
            detail_score += 1
        if len(bullet_lines) >= 2:
            detail_score += 2
        if constraint_hit_count >= 4:
            detail_score += 2

        is_detailed = detail_score >= 3
        return {
            "fidelity_mode": "strict" if is_detailed else "standard",
            "is_user_input_detailed": is_detailed,
            "expansion_scope": (
                "只允许镜头化整理、节奏压缩和必要衔接，不允许新增支线、反转、背景设定或额外角色"
                if is_detailed
                else "可以做少量必要补全，但不要改写核心设定"
            ),
            "preserve_points": self._extract_user_input_preserve_points(
                normalized_input,
                lines=lines,
                sentence_candidates=sentence_candidates,
            ),
            "temperature": 0.1 if is_detailed else 0.2,
        }

    def _extract_user_input_preserve_points(
        self,
        user_input: str,
        *,
        lines: Optional[List[str]] = None,
        sentence_candidates: Optional[List[str]] = None,
    ) -> List[str]:
        normalized_input = str(user_input or "").strip()
        if not normalized_input:
            return []

        candidate_lines = list(lines or [line.strip() for line in re.split(r"\r?\n+", normalized_input) if line.strip()])
        candidate_sentences = list(
            sentence_candidates
            or [sentence.strip() for sentence in re.split(r"[\n。！？!?；;]+", normalized_input) if sentence.strip()]
        )
        priority_keywords = (
            "必须",
            "不要",
            "不能",
            "角色",
            "关系",
            "地点",
            "时间",
            "结局",
            "场景",
            "对白",
            "镜头",
            "设定",
        )
        prioritized: List[str] = []
        fallback: List[str] = []
        for raw_candidate in [*candidate_lines, *candidate_sentences]:
            normalized_candidate = self._normalize_preserve_point(raw_candidate)
            if not normalized_candidate:
                continue
            target = prioritized if any(keyword in normalized_candidate for keyword in priority_keywords) else fallback
            if normalized_candidate not in prioritized and normalized_candidate not in fallback:
                target.append(normalized_candidate)

        selected = [*prioritized, *fallback][:8]
        if selected:
            return selected
        fallback_point = self._truncate_text(normalized_input, 80)
        return [fallback_point] if fallback_point else []

    def _normalize_preserve_point(self, text: str) -> str:
        normalized = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", str(text or "").strip())
        normalized = re.sub(r"\s+", " ", normalized).strip("，。；; ")
        if len(normalized) < 4:
            return ""
        return self._truncate_text(normalized, 80)

    def _merge_correction_note_with_input_fidelity(self, correction_note: str, *, user_input: str) -> str:
        note = str(correction_note or "").strip()
        if not note:
            return ""
        policy = self._build_script_input_policy(user_input)
        if policy["fidelity_mode"] == "strict":
            fidelity_note = (
                "除本次必要修正外，不要改写用户输入中已明确给出的剧情事实、角色关系、时间地点、事件顺序和结局。"
                " 当前输入信息较详细，按保守改写处理：只做镜头化整理和必要衔接，不新增支线、反转、前史、世界观补充或额外设定。"
            )
        else:
            fidelity_note = "除本次必要修正外，不要改写用户输入中的核心设定和剧情主线。"
        return f"{note} {fidelity_note}".strip()

    def _build_scene_constraint_card(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": profile.get("id", ""),
            "name": profile.get("name", ""),
            "profile_version": profile.get("profile_version", 1),
            "category": profile.get("category", ""),
            "scene_type": profile.get("scene_type", ""),
            "story_function": profile.get("story_function", ""),
            "llm_summary": profile.get("llm_summary") or self._truncate_text(
                "；".join(
                    part
                    for part in [
                        profile.get("description"),
                        profile.get("location"),
                        profile.get("atmosphere"),
                        profile.get("scene_rules"),
                    ]
                    if part
                ),
                240,
            ),
            "must_have": self._normalize_list(profile.get("must_have_elements") or profile.get("props_must_have") or []),
            "forbidden": self._normalize_list(profile.get("forbidden_elements") or profile.get("props_forbidden") or []),
        }

    def _score_profile(
        self,
        *,
        profile_type: str,
        profile: Dict[str, Any],
        query: Dict[str, Any],
        user_input: str,
    ) -> float:
        haystack_fields = [
            profile.get("name"),
            profile.get("category"),
            profile.get("role"),
            profile.get("archetype"),
            profile.get("scene_type"),
            profile.get("story_function"),
            profile.get("description"),
            profile.get("llm_summary"),
            profile.get("tags"),
            profile.get("aliases"),
        ]
        haystack = " ".join(
            item if isinstance(item, str) else " ".join(str(v) for v in (item or []))
            for item in haystack_fields
            if item
        ).lower()

        score = 0.0
        keywords = [str(item).strip().lower() for item in (query.get("keywords") or []) if str(item).strip()]
        for key in keywords:
            if key and key in haystack:
                score += 2.0
        if str(query.get("category") or "").strip().lower() and str(query.get("category")).strip().lower() == str(profile.get("category") or "").strip().lower():
            score += 3.0
        if profile_type == "character":
            for key in [query.get("role"), query.get("archetype"), query.get("name_hint")]:
                key_text = str(key or "").strip().lower()
                if key_text and key_text in haystack:
                    score += 2.5
        else:
            for key in [query.get("scene_type"), query.get("story_function"), query.get("name_hint")]:
                key_text = str(key or "").strip().lower()
                if key_text and key_text in haystack:
                    score += 2.5

        if not score:
            user_tokens = self._tokenize(user_input)
            overlap = sum(1 for token in user_tokens if token and token in haystack)
            score += overlap * 0.3
        return score

    def _normalize_character_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(profile)
        normalized["tags"] = self._normalize_list(normalized.get("tags") or [])
        normalized["aliases"] = self._normalize_list(normalized.get("aliases") or [])
        normalized["must_keep"] = self._normalize_list(normalized.get("must_keep") or [])
        normalized["forbidden_traits"] = self._normalize_list(normalized.get("forbidden_traits") or [])
        normalized["voice_description"] = str(normalized.get("voice_description") or "").strip()
        normalized["profile_version"] = self._safe_int(normalized.get("profile_version"), default=1)
        return normalized

    def _normalize_scene_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(profile)
        for key in [
            "tags",
            "allowed_characters",
            "props_must_have",
            "props_forbidden",
            "must_have_elements",
            "forbidden_elements",
            "camera_preferences",
        ]:
            normalized[key] = self._normalize_list(normalized.get(key) or [])
        normalized["profile_version"] = self._safe_int(normalized.get("profile_version"), default=1)
        return normalized

    def _match_character_from_output(
        self,
        raw: Dict[str, Any],
        lookup: Dict[str, Dict[str, Any]],
        name_lookup: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        profile_id = str(raw.get("character_profile_id") or "").strip()
        if profile_id and profile_id in lookup:
            return lookup[profile_id]
        normalized_name = self._normalize_name(raw.get("name"))
        return name_lookup.get(normalized_name, {})

    def _match_scene_from_output(
        self,
        raw: Dict[str, Any],
        lookup: Dict[str, Dict[str, Any]],
        name_lookup: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        profile_id = str(raw.get("scene_profile_id") or "").strip()
        if profile_id and profile_id in lookup:
            return lookup[profile_id]
        normalized_name = self._normalize_name(raw.get("title") or raw.get("location"))
        return name_lookup.get(normalized_name, {})

    def _match_character_ids_from_shot(
        self,
        *,
        shot_data: Dict[str, Any],
        actions: List[ActionDetail],
        dialogues: List[DialogueLine],
        characters: List[CharacterInfo],
        output_name_to_profile_id: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        name_to_id = {self._normalize_name(character.name): character.profile_id for character in characters if character.profile_id}
        if output_name_to_profile_id:
            for normalized_name, profile_id in output_name_to_profile_id.items():
                if normalized_name and profile_id:
                    name_to_id.setdefault(normalized_name, profile_id)
        candidates = self._normalize_list(shot_data.get("characters_in_shot") or [])
        candidates.extend(action.character for action in actions if action.character)
        candidates.extend(dialogue.speaker for dialogue in dialogues if dialogue.speaker)
        resolved: List[str] = []
        for candidate in candidates:
            profile_id = name_to_id.get(self._normalize_name(candidate))
            if profile_id and profile_id not in resolved:
                resolved.append(profile_id)
        return resolved

    def _canonicalize_character_name(
        self,
        value: str,
        *,
        output_name_to_profile_id: Dict[str, str],
        profile_id_to_canonical_name: Dict[str, str],
    ) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        profile_id = output_name_to_profile_id.get(self._normalize_name(raw_value))
        canonical_name = profile_id_to_canonical_name.get(profile_id or "")
        return canonical_name or raw_value

    def _canonicalize_name_list(
        self,
        values: List[str],
        *,
        output_name_to_profile_id: Dict[str, str],
        profile_id_to_canonical_name: Dict[str, str],
    ) -> List[str]:
        normalized: List[str] = []
        for value in values:
            canonical = self._canonicalize_character_name(
                value,
                output_name_to_profile_id=output_name_to_profile_id,
                profile_id_to_canonical_name=profile_id_to_canonical_name,
            )
            if canonical and canonical not in normalized:
                normalized.append(canonical)
        return normalized

    def _canonicalize_actions(
        self,
        actions: List[ActionDetail],
        *,
        output_name_to_profile_id: Dict[str, str],
        profile_id_to_canonical_name: Dict[str, str],
    ) -> List[ActionDetail]:
        for action in actions:
            action.character = self._canonicalize_character_name(
                action.character,
                output_name_to_profile_id=output_name_to_profile_id,
                profile_id_to_canonical_name=profile_id_to_canonical_name,
            )
        return actions

    def _canonicalize_dialogues(
        self,
        dialogues: List[DialogueLine],
        *,
        output_name_to_profile_id: Dict[str, str],
        profile_id_to_canonical_name: Dict[str, str],
    ) -> List[DialogueLine]:
        for dialogue in dialogues:
            dialogue.speaker = self._canonicalize_character_name(
                dialogue.speaker,
                output_name_to_profile_id=output_name_to_profile_id,
                profile_id_to_canonical_name=profile_id_to_canonical_name,
            )
        return dialogues

    def _normalize_profile_version_map(
        self,
        raw_map: Dict[str, Any],
        *,
        characters: List[CharacterInfo],
        character_profile_ids: List[str],
    ) -> Dict[str, int]:
        result = {}
        if isinstance(raw_map, dict):
            for key, value in raw_map.items():
                profile_id = str(key).strip()
                if profile_id:
                    result[profile_id] = self._safe_int(value, default=1)
        if result:
            return result
        lookup = {character.profile_id: character.profile_version for character in characters if character.profile_id}
        return {profile_id: lookup.get(profile_id, 1) for profile_id in character_profile_ids}

    def _normalize_scene_shots(self, scene: SceneInfo) -> List[ShotInfo]:
        cleaned: List[ShotInfo] = []
        for shot in scene.shots:
            if not self._shot_has_meaningful_content(shot):
                continue
            shot.duration = max(1.0, float(shot.duration or 0.0))
            if not shot.scene_profile_id:
                shot.scene_profile_id = scene.scene_profile_id
            if not shot.scene_profile_version:
                shot.scene_profile_version = scene.scene_profile_version
            cleaned.append(shot)

        if not cleaned:
            return []

        total_duration = sum(shot.duration for shot in cleaned)
        target_shot_count = self._estimate_reasonable_shot_count(scene, total_duration)
        if len(cleaned) > target_shot_count + 1 and self._looks_like_templated_shot_layout(cleaned):
            cleaned = self._merge_low_information_shots(cleaned, target_shot_count)

        for index, shot in enumerate(cleaned, start=1):
            shot.shot_number = index
        return cleaned

    def _shot_has_meaningful_content(self, shot: ShotInfo) -> bool:
        return bool(
            shot.description.strip()
            or shot.actions
            or shot.dialogues
            or shot.characters_in_shot
            or shot.environment.strip()
            or shot.prompt_focus.strip()
        )

    def _estimate_reasonable_shot_count(self, scene: SceneInfo, total_duration: float) -> int:
        base = max(2, math.ceil(total_duration / 3.5))
        richness_score = 0
        for shot in scene.shots:
            if shot.actions:
                richness_score += 1
            if shot.dialogues:
                richness_score += 1
            if shot.camera_movement.strip():
                richness_score += 1
            if shot.prompt_focus.strip():
                richness_score += 1
        if any(keyword in (scene.scene_type or "") for keyword in ["高潮", "冲突", "战斗", "追逐"]):
            base += 1
        if richness_score >= 8:
            base += 1
        return max(2, min(base, 8))

    def _looks_like_templated_shot_layout(self, shots: List[ShotInfo]) -> bool:
        if len(shots) < 5:
            return False
        short_shots = sum(1 for shot in shots if shot.duration <= 3.0)
        low_info_shots = sum(
            1
            for shot in shots
            if len((shot.description or "").strip()) < 24 and not shot.dialogues and len(shot.actions) <= 1
        )
        repeated_types = len({(shot.shot_type or "").strip() for shot in shots}) <= 2
        return short_shots >= len(shots) - 1 and low_info_shots >= len(shots) - 2 and repeated_types

    def _merge_low_information_shots(self, shots: List[ShotInfo], target_count: int) -> List[ShotInfo]:
        merged = list(shots)
        while len(merged) > target_count:
            merge_index = self._pick_merge_candidate(merged)
            if merge_index is None:
                break
            current = merged[merge_index]
            nxt = merged[merge_index + 1]
            combined_ids = list(dict.fromkeys([*current.character_profile_ids, *nxt.character_profile_ids]))
            combined_versions = {**current.character_profile_versions, **nxt.character_profile_versions}
            merged_shot = ShotInfo(
                shot_number=current.shot_number,
                duration=round(current.duration + nxt.duration, 1),
                scene_profile_id=current.scene_profile_id or nxt.scene_profile_id,
                scene_profile_version=current.scene_profile_version or nxt.scene_profile_version,
                character_profile_ids=combined_ids,
                character_profile_versions=combined_versions,
                prompt_focus=self._combine_text(current.prompt_focus, nxt.prompt_focus),
                shot_type=current.shot_type or nxt.shot_type,
                camera_angle=current.camera_angle or nxt.camera_angle,
                camera_movement=current.camera_movement or nxt.camera_movement,
                description=self._combine_text(current.description, nxt.description),
                environment=self._combine_text(current.environment, nxt.environment),
                lighting=current.lighting or nxt.lighting,
                characters_in_shot=list(dict.fromkeys([*current.characters_in_shot, *nxt.characters_in_shot])),
                actions=[*current.actions, *nxt.actions],
                dialogues=[*current.dialogues, *nxt.dialogues],
                sound_effects=list(dict.fromkeys([*current.sound_effects, *nxt.sound_effects])),
                music=current.music or nxt.music,
            )
            merged = [*merged[:merge_index], merged_shot, *merged[merge_index + 2 :]]
        return merged

    def _pick_merge_candidate(self, shots: List[ShotInfo]) -> Optional[int]:
        best_index: Optional[int] = None
        best_score: Optional[float] = None
        for index in range(len(shots) - 1):
            current = shots[index]
            nxt = shots[index + 1]
            score = (
                current.duration
                + nxt.duration
                + (0.6 if not current.dialogues and not nxt.dialogues else 0.0)
                + (0.6 if len(current.actions) + len(nxt.actions) <= 2 else 0.0)
                + (0.4 if (current.shot_type or "") == (nxt.shot_type or "") else 0.0)
            )
            if best_score is None or score < best_score:
                best_score = score
                best_index = index
        return best_index

    def _combine_text(self, left: str, right: str) -> str:
        left = (left or "").strip()
        right = (right or "").strip()
        if not left:
            return right
        if not right:
            return left
        if right in left:
            return left
        return f"{left}；{right}"

    def _validate_full_script(self, script: FullScript) -> None:
        if not script.title.strip():
            raise ValueError("生成结果缺少标题")
        if not script.scenes:
            raise ValueError("生成结果缺少场景")
        total_shots = sum(len(scene.shots) for scene in script.scenes)
        if total_shots <= 0:
            raise ValueError("生成结果缺少分镜")
        late_entry_risks = self._collect_shot_late_entry_risks(script)
        if late_entry_risks:
            logger.warning(
                "剧本存在疑似镜头内新角色中途入场风险，共 %s 处: %s",
                len(late_entry_risks),
                " | ".join(late_entry_risks[:8]),
            )

    def _collect_shot_late_entry_risks(self, script: FullScript) -> List[str]:
        risks: List[str] = []
        for scene in script.scenes:
            for shot in scene.shots:
                evidence = self._extract_shot_late_entry_evidence(shot)
                if not evidence:
                    continue
                risks.append(
                    f"场景{scene.scene_number}-镜头{shot.shot_number}: {evidence}"
                )
        return risks

    def _extract_shot_late_entry_evidence(self, shot: ShotInfo) -> str:
        text_parts = [
            str(shot.description or "").strip(),
            str(shot.prompt_focus or "").strip(),
        ]
        text_parts.extend(str(action.action_name or "").strip() for action in shot.actions)
        text_parts.extend(str(action.description or "").strip() for action in shot.actions)
        merged_text = " ".join(part for part in text_parts if part).lower()
        if not merged_text:
            return ""
        for keyword in sorted(SHOT_LATE_ENTRY_KEYWORDS, key=len, reverse=True):
            if keyword.lower() in merged_text:
                return keyword
        return ""

    def _rebalance_script_duration(self, script: FullScript, target_total_duration: float) -> None:
        shots = [shot for scene in script.scenes for shot in scene.shots]
        if not shots:
            return
        current_duration = sum(float(shot.duration or 0.0) for shot in shots)
        if current_duration <= 0:
            return
        original_durations = [max(1.0, float(shot.duration or 1.0)) for shot in shots]
        scaled = [max(1.0, round(value * target_total_duration / current_duration, 1)) for value in original_durations]
        delta = round(float(target_total_duration) - sum(scaled), 1)
        direction = 1 if delta > 0 else -1 if delta < 0 else 0
        shot_order = sorted(range(len(shots)), key=lambda index: original_durations[index], reverse=(direction > 0))
        step = 0.1 if direction > 0 else -0.1
        while direction != 0 and abs(delta) >= 0.1 and shot_order:
            adjusted = False
            for index in shot_order:
                candidate = round(scaled[index] + step, 1)
                if candidate < 1.0:
                    continue
                scaled[index] = candidate
                delta = round(delta - step, 1)
                adjusted = True
                if abs(delta) < 0.1:
                    break
            if not adjusted:
                break
        for shot, duration in zip(shots, scaled):
            shot.duration = round(duration, 1)
        script.total_duration = round(sum(scaled), 1)

    def _duration_tolerance(self, target_total_duration: float) -> float:
        return max(1.0, min(3.0, float(target_total_duration) * 0.1))

    def _duration_within_tolerance(self, current_duration: float, target_total_duration: float, tolerance: float) -> bool:
        return abs(float(current_duration) - float(target_total_duration)) <= tolerance

    def _parse_llm_json(self, content: str) -> dict:
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
        snippet = content[:1500]
        raise ValueError(f"无法解析LLM返回的JSON。errors={parse_errors[:4]} raw={snippet}")

    def _build_json_candidates(self, content: str) -> List[str]:
        raw = content.strip()
        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        object_match = re.search(r"\{.*\}", raw, re.DOTALL)
        candidates: List[str] = []
        for value in [raw, fenced_match.group(1) if fenced_match else "", object_match.group(0) if object_match else ""]:
            if value:
                candidates.extend(self._expand_json_variants(value))
        deduped: List[str] = []
        seen = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return deduped

    def _expand_json_variants(self, value: str) -> List[str]:
        stripped = value.strip()
        without_comments = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
        without_comments = re.sub(r"(?m)^\s*//.*$", "", without_comments)
        without_trailing_commas = re.sub(r",(\s*[}\]])", r"\1", without_comments)
        no_fences = without_trailing_commas.replace("```json", "").replace("```", "").strip()
        return [stripped, without_comments.strip(), without_trailing_commas.strip(), no_fences]

    def _convert_json_literals_to_python(self, value: str) -> str:
        converted = re.sub(r"\btrue\b", "True", value)
        converted = re.sub(r"\bfalse\b", "False", converted)
        converted = re.sub(r"\bnull\b", "None", converted)
        return converted

    def _tokenize(self, text: str) -> List[str]:
        raw_tokens = re.split(r"[\s,，。！？；：:、/|]+", str(text or ""))
        return [token.strip().lower() for token in raw_tokens if len(token.strip()) >= 2]

    def _normalize_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = re.split(r"[\n,，]", value)
        else:
            items = list(value)
        return [str(item).strip() for item in items if str(item).strip()]

    def _safe_float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: Any, *, default: int) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            normalized = int(default)
        return normalized if normalized > 0 else int(default)

    def _truncate_text(self, text: str, limit: int) -> str:
        normalized = str(text or "").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    def _normalize_name(self, value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "").strip().lower())


async def generate_script_from_input(user_input: str) -> FullScript:
    generator = ScriptGenerator()
    return await generator.generate_full_script(user_input)
