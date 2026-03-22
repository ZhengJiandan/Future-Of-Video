#!/usr/bin/env python3
"""图片分析服务：将角色/场景参考图补充为结构化档案字段。"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ProfileImageAnalyzerService:
    def __init__(self) -> None:
        self.api_key = getattr(settings, "DOUBAO_API_KEY", None)
        self.base_url = str(getattr(settings, "DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")).rstrip("/")
        self.model = str(getattr(settings, "DOUBAO_MODEL", "doubao-seed-2-0-lite-260215")).strip() or "doubao-seed-2-0-lite-260215"
        self.timeout = httpx.Timeout(
            connect=float(getattr(settings, "DOUBAO_CONNECT_TIMEOUT", 20.0)),
            read=float(getattr(settings, "DOUBAO_READ_TIMEOUT", 240.0)),
            write=float(getattr(settings, "DOUBAO_WRITE_TIMEOUT", 60.0)),
            pool=float(getattr(settings, "DOUBAO_POOL_TIMEOUT", 60.0)),
        )

    async def analyze_character_image(
        self,
        *,
        image_path: Path,
        filename: str = "",
    ) -> Dict[str, Any]:
        schema = {
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
            "forbidden_behaviors": "",
            "prompt_hint": "",
            "llm_summary": "",
            "image_prompt_base": "",
            "video_prompt_base": "",
            "negative_prompt": "",
            "tags": [],
            "must_keep": [],
            "forbidden_traits": [],
            "aliases": [],
        }
        system_prompt = """你是角色档案分析助手。请根据用户上传的单张角色图片，输出适合内部角色档案的结构化字段。

规则：
1. 只输出合法 JSON，不要输出解释文字。
2. 不能确定的字段留空字符串，数组留空数组，不要编造具体姓名或世界观。
3. 重点提炼稳定外观锚点、服装、发型、脸部特征、体态、配色和角色气质。
4. llm_summary 用 80-180 字概括，便于后续剧本模型稳定引用。
5. image_prompt_base 和 video_prompt_base 要适合直接给图像/视频模型做稳定提示。
6. tags / must_keep / forbidden_traits / aliases 必须是字符串数组。
7. 图片不能可靠判断声音设定，不要硬写音色相关内容，本任务不输出 voice_description。
"""
        user_prompt = (
            "请分析这张角色图片，按给定 JSON 结构补全字段。"
            f" 原文件名: {filename or image_path.name}。"
            " 如果是卡通、写实、概念设计或游戏角色，都按画面中可见信息提炼。"
            f"\n目标 JSON 结构：{json.dumps(schema, ensure_ascii=False)}"
        )
        result = await self._analyze_with_image(
            image_path=image_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return self._normalize_character_result(result)

    async def analyze_scene_image(
        self,
        *,
        image_path: Path,
        filename: str = "",
    ) -> Dict[str, Any]:
        schema = {
            "name": "",
            "category": "",
            "scene_type": "",
            "description": "",
            "story_function": "",
            "location": "",
            "scene_rules": "",
            "time_setting": "",
            "weather": "",
            "lighting": "",
            "atmosphere": "",
            "architecture_style": "",
            "color_palette": "",
            "prompt_hint": "",
            "llm_summary": "",
            "image_prompt_base": "",
            "video_prompt_base": "",
            "negative_prompt": "",
            "tags": [],
            "allowed_characters": [],
            "props_must_have": [],
            "props_forbidden": [],
            "must_have_elements": [],
            "forbidden_elements": [],
            "camera_preferences": [],
        }
        system_prompt = """你是场景档案分析助手。请根据用户上传的单张场景图片，输出适合内部场景档案的结构化字段。

规则：
1. 只输出合法 JSON，不要输出解释文字。
2. 不能确定的字段留空字符串，数组留空数组，不要编造具体剧情。
3. 重点提炼地点类型、时间、天气、灯光、氛围、建筑风格、场景规则、构图与镜头偏好。
4. llm_summary 用 80-180 字概括，便于后续剧本模型稳定引用。
5. image_prompt_base 和 video_prompt_base 要适合直接给图像/视频模型做稳定提示。
6. tags / allowed_characters / props_must_have / props_forbidden / must_have_elements / forbidden_elements / camera_preferences 必须是字符串数组。
"""
        user_prompt = (
            "请分析这张场景图片，按给定 JSON 结构补全字段。"
            f" 原文件名: {filename or image_path.name}。"
            " 如果是室内、室外、概念场景、插画场景或写实照片，都按画面中可见信息提炼。"
            f"\n目标 JSON 结构：{json.dumps(schema, ensure_ascii=False)}"
        )
        result = await self._analyze_with_image(
            image_path=image_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return self._normalize_scene_result(result)

    async def _analyze_with_image(
        self,
        *,
        image_path: Path,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("DOUBAO_API_KEY 未配置，暂时无法分析图片")
        if not image_path.exists():
            raise ValueError("图片不存在，无法分析")

        image_url = self._build_data_url(image_path)
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "temperature": 0.2,
        }
        payload = await self._request_completion(request_body)
        content = self._extract_message_content(payload)
        if not content:
            raise RuntimeError("图片分析模型返回为空")
        return self._parse_json_payload(content)

    async def _request_completion(self, request_body: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=request_body,
            )
            response.raise_for_status()
            return response.json()

    def _extract_message_content(self, payload: Dict[str, Any]) -> str:
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = str(item.get("text") or item.get("content") or "").strip()
                    if text_value:
                        parts.append(text_value)
            return "\n".join(parts).strip()
        return str(content or "").strip()

    def _parse_json_payload(self, content: str) -> Dict[str, Any]:
        normalized = str(content or "").strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3:
                normalized = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as exc:
            start = normalized.find("{")
            end = normalized.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(normalized[start : end + 1])
                except json.JSONDecodeError as inner_exc:
                    raise RuntimeError(f"图片分析结果不是合法 JSON: {inner_exc}") from inner_exc
            else:
                raise RuntimeError(f"图片分析结果不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("图片分析结果不是 JSON 对象")
        return parsed

    def _build_data_url(self, image_path: Path) -> str:
        raw = image_path.read_bytes()
        suffix = image_path.suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "image/png")
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('utf-8')}"

    def _normalize_text(self, value: Any) -> str:
        return str(value or "").strip()

    def _normalize_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = str(value).replace("，", ",").replace("、", ",").split(",")
        result: List[str] = []
        for item in items:
            normalized = str(item or "").strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    def _normalize_character_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": self._normalize_text(payload.get("name")),
            "category": self._normalize_text(payload.get("category")),
            "role": self._normalize_text(payload.get("role")),
            "archetype": self._normalize_text(payload.get("archetype")),
            "age_range": self._normalize_text(payload.get("age_range")),
            "gender_presentation": self._normalize_text(payload.get("gender_presentation")),
            "description": self._normalize_text(payload.get("description")),
            "appearance": self._normalize_text(payload.get("appearance")),
            "personality": self._normalize_text(payload.get("personality")),
            "core_appearance": self._normalize_text(payload.get("core_appearance")),
            "hair": self._normalize_text(payload.get("hair")),
            "face_features": self._normalize_text(payload.get("face_features")),
            "body_shape": self._normalize_text(payload.get("body_shape")),
            "outfit": self._normalize_text(payload.get("outfit")),
            "gear": self._normalize_text(payload.get("gear")),
            "color_palette": self._normalize_text(payload.get("color_palette")),
            "visual_do_not_change": self._normalize_text(payload.get("visual_do_not_change")),
            "speaking_style": self._normalize_text(payload.get("speaking_style")),
            "common_actions": self._normalize_text(payload.get("common_actions")),
            "emotion_baseline": self._normalize_text(payload.get("emotion_baseline")),
            "forbidden_behaviors": self._normalize_text(payload.get("forbidden_behaviors")),
            "prompt_hint": self._normalize_text(payload.get("prompt_hint")),
            "llm_summary": self._normalize_text(payload.get("llm_summary")),
            "image_prompt_base": self._normalize_text(payload.get("image_prompt_base")),
            "video_prompt_base": self._normalize_text(payload.get("video_prompt_base")),
            "negative_prompt": self._normalize_text(payload.get("negative_prompt")),
            "tags": self._normalize_list(payload.get("tags")),
            "must_keep": self._normalize_list(payload.get("must_keep")),
            "forbidden_traits": self._normalize_list(payload.get("forbidden_traits")),
            "aliases": self._normalize_list(payload.get("aliases")),
        }

    def _normalize_scene_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": self._normalize_text(payload.get("name")),
            "category": self._normalize_text(payload.get("category")),
            "scene_type": self._normalize_text(payload.get("scene_type")),
            "description": self._normalize_text(payload.get("description")),
            "story_function": self._normalize_text(payload.get("story_function")),
            "location": self._normalize_text(payload.get("location")),
            "scene_rules": self._normalize_text(payload.get("scene_rules")),
            "time_setting": self._normalize_text(payload.get("time_setting")),
            "weather": self._normalize_text(payload.get("weather")),
            "lighting": self._normalize_text(payload.get("lighting")),
            "atmosphere": self._normalize_text(payload.get("atmosphere")),
            "architecture_style": self._normalize_text(payload.get("architecture_style")),
            "color_palette": self._normalize_text(payload.get("color_palette")),
            "prompt_hint": self._normalize_text(payload.get("prompt_hint")),
            "llm_summary": self._normalize_text(payload.get("llm_summary")),
            "image_prompt_base": self._normalize_text(payload.get("image_prompt_base")),
            "video_prompt_base": self._normalize_text(payload.get("video_prompt_base")),
            "negative_prompt": self._normalize_text(payload.get("negative_prompt")),
            "tags": self._normalize_list(payload.get("tags")),
            "allowed_characters": self._normalize_list(payload.get("allowed_characters")),
            "props_must_have": self._normalize_list(payload.get("props_must_have")),
            "props_forbidden": self._normalize_list(payload.get("props_forbidden")),
            "must_have_elements": self._normalize_list(payload.get("must_have_elements")),
            "forbidden_elements": self._normalize_list(payload.get("forbidden_elements")),
            "camera_preferences": self._normalize_list(payload.get("camera_preferences")),
        }


profile_image_analyzer_service = ProfileImageAnalyzerService()
