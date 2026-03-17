#!/usr/bin/env python3
"""数据库持久化的主链路场景档案服务。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.pipeline_scene_profile import PipelineSceneProfile
from app.services.nanobanana_pro import NanoBananaProClient


class PipelineSceneLibraryService:
    def __init__(self) -> None:
        self.library_root = Path(settings.UPLOAD_DIR) / "generated" / "pipeline" / "scene_library"
        self.reference_root = self.library_root / "references"
        self.prototype_root = self.library_root / "prototypes"
        self.reference_root.mkdir(parents=True, exist_ok=True)
        self.prototype_root.mkdir(parents=True, exist_ok=True)
        self.nanobanana = NanoBananaProClient()

    async def list_profiles(self, db: AsyncSession) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineSceneProfile).order_by(
                PipelineSceneProfile.updated_at.desc(),
                PipelineSceneProfile.created_at.desc(),
            )
        )
        return [item.to_dict() for item in result.scalars().all()]

    async def get_profile_by_id(self, db: AsyncSession, profile_id: str) -> Optional[Dict[str, Any]]:
        normalized_id = str(profile_id or "").strip()
        if not normalized_id:
            return None

        result = await db.execute(
            select(PipelineSceneProfile).where(PipelineSceneProfile.id == normalized_id)
        )
        profile = result.scalar_one_or_none()
        return profile.to_dict() if profile else None

    async def get_profiles_by_ids(self, db: AsyncSession, profile_ids: List[str]) -> List[Dict[str, Any]]:
        normalized_ids = [str(item).strip() for item in profile_ids if str(item).strip()]
        if not normalized_ids:
            return []

        result = await db.execute(
            select(PipelineSceneProfile).where(PipelineSceneProfile.id.in_(normalized_ids))
        )
        lookup = {item.id: item.to_dict() for item in result.scalars().all()}
        return [lookup[profile_id] for profile_id in normalized_ids if profile_id in lookup]

    async def create_profile(self, db: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("场景名称不能为空")

        now = datetime.utcnow()
        profile = PipelineSceneProfile(
            id=uuid.uuid4().hex,
            name=name,
            category=str(payload.get("category") or "").strip(),
            scene_type=str(payload.get("scene_type") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            story_function=str(payload.get("story_function") or "").strip(),
            location=str(payload.get("location") or "").strip(),
            scene_rules=str(payload.get("scene_rules") or "").strip(),
            time_setting=str(payload.get("time_setting") or "").strip(),
            weather=str(payload.get("weather") or "").strip(),
            lighting=str(payload.get("lighting") or "").strip(),
            atmosphere=str(payload.get("atmosphere") or "").strip(),
            architecture_style=str(payload.get("architecture_style") or "").strip(),
            color_palette=str(payload.get("color_palette") or "").strip(),
            prompt_hint=str(payload.get("prompt_hint") or "").strip(),
            llm_summary=str(payload.get("llm_summary") or "").strip(),
            image_prompt_base=str(payload.get("image_prompt_base") or "").strip(),
            video_prompt_base=str(payload.get("video_prompt_base") or "").strip(),
            negative_prompt=str(payload.get("negative_prompt") or "").strip(),
            tags=self._normalize_tags(payload.get("tags") or []),
            allowed_characters=self._normalize_list_field(payload.get("allowed_characters") or []),
            props_must_have=self._normalize_list_field(payload.get("props_must_have") or []),
            props_forbidden=self._normalize_list_field(payload.get("props_forbidden") or []),
            must_have_elements=self._normalize_list_field(payload.get("must_have_elements") or []),
            forbidden_elements=self._normalize_list_field(payload.get("forbidden_elements") or []),
            camera_preferences=self._normalize_list_field(payload.get("camera_preferences") or []),
            profile_version=self._normalize_profile_version(payload.get("profile_version")),
            source=str(payload.get("source") or "library").strip() or "library",
            reference_image_url=str(payload.get("reference_image_url") or "").strip() or None,
            reference_image_path=self._asset_url_to_db_path(str(payload.get("reference_image_url") or "").strip()),
            reference_image_original_name=str(payload.get("reference_image_original_name") or "").strip() or None,
            created_at=now,
            updated_at=now,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile.to_dict()

    async def update_profile(
        self,
        db: AsyncSession,
        profile_id: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        normalized_id = str(profile_id or "").strip()
        if not normalized_id:
            raise ValueError("场景档案不存在")

        result = await db.execute(select(PipelineSceneProfile).where(PipelineSceneProfile.id == normalized_id))
        profile = result.scalar_one_or_none()
        if not profile:
            return None

        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("场景名称不能为空")

        original_reference_image_path = profile.reference_image_path or ""
        original_reference_image_url = profile.reference_image_url or ""
        final_reference_image_url = str(payload.get("reference_image_url") or "").strip()

        profile.name = name
        profile.category = str(payload.get("category") or "").strip()
        profile.scene_type = str(payload.get("scene_type") or "").strip()
        profile.description = str(payload.get("description") or "").strip()
        profile.story_function = str(payload.get("story_function") or "").strip()
        profile.location = str(payload.get("location") or "").strip()
        profile.scene_rules = str(payload.get("scene_rules") or "").strip()
        profile.time_setting = str(payload.get("time_setting") or "").strip()
        profile.weather = str(payload.get("weather") or "").strip()
        profile.lighting = str(payload.get("lighting") or "").strip()
        profile.atmosphere = str(payload.get("atmosphere") or "").strip()
        profile.architecture_style = str(payload.get("architecture_style") or "").strip()
        profile.color_palette = str(payload.get("color_palette") or "").strip()
        profile.prompt_hint = str(payload.get("prompt_hint") or "").strip()
        profile.llm_summary = str(payload.get("llm_summary") or "").strip()
        profile.image_prompt_base = str(payload.get("image_prompt_base") or "").strip()
        profile.video_prompt_base = str(payload.get("video_prompt_base") or "").strip()
        profile.negative_prompt = str(payload.get("negative_prompt") or "").strip()
        profile.tags = self._normalize_tags(payload.get("tags") or [])
        profile.allowed_characters = self._normalize_list_field(payload.get("allowed_characters") or [])
        profile.props_must_have = self._normalize_list_field(payload.get("props_must_have") or [])
        profile.props_forbidden = self._normalize_list_field(payload.get("props_forbidden") or [])
        profile.must_have_elements = self._normalize_list_field(payload.get("must_have_elements") or [])
        profile.forbidden_elements = self._normalize_list_field(payload.get("forbidden_elements") or [])
        profile.camera_preferences = self._normalize_list_field(payload.get("camera_preferences") or [])
        profile.profile_version = self._normalize_profile_version(payload.get("profile_version"))
        profile.source = str(payload.get("source") or "library").strip() or "library"
        profile.reference_image_url = final_reference_image_url or None
        profile.reference_image_path = self._asset_url_to_db_path(final_reference_image_url)
        profile.reference_image_original_name = (
            str(payload.get("reference_image_original_name") or "").strip() or None
        )
        profile.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(profile)

        if (
            original_reference_image_path
            and original_reference_image_url != final_reference_image_url
            and original_reference_image_path != profile.reference_image_path
        ):
            self._delete_local_asset(original_reference_image_path)

        return profile.to_dict()

    async def delete_profile(self, db: AsyncSession, profile_id: str) -> bool:
        result = await db.execute(select(PipelineSceneProfile).where(PipelineSceneProfile.id == profile_id))
        profile = result.scalar_one_or_none()
        if not profile:
            return False

        self._delete_local_asset(profile.reference_image_path)
        await db.execute(delete(PipelineSceneProfile).where(PipelineSceneProfile.id == profile_id))
        await db.commit()
        return True

    async def save_reference_upload(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> Dict[str, Any]:
        asset_id = uuid.uuid4().hex
        suffix = self._guess_suffix(filename, content_type)
        safe_name = f"{asset_id}_scene_reference{suffix}"
        output_path = self.reference_root / safe_name
        output_path.write_bytes(content)
        return {
            "id": asset_id,
            "url": self._build_asset_url(output_path),
            "filename": safe_name,
            "original_filename": filename,
            "content_type": content_type,
            "size": len(content),
            "source": "scene-reference-upload",
        }

    async def generate_scene_image_asset(
        self,
        *,
        base_image_url: str = "",
        name: str = "",
        scene_type: str = "",
        description: str = "",
        story_function: str = "",
        location: str = "",
        time_setting: str = "",
        weather: str = "",
        lighting: str = "",
        atmosphere: str = "",
        architecture_style: str = "",
        color_palette: str = "",
        scene_rules: str = "",
        prompt_hint: str = "",
        llm_summary: str = "",
        image_prompt_base: str = "",
        refine_prompt: str = "",
    ) -> Dict[str, Any]:
        base_path = self._asset_url_to_path(base_image_url)
        prompt = self._build_scene_image_prompt(
            name=name,
            scene_type=scene_type,
            description=description,
            story_function=story_function,
            location=location,
            time_setting=time_setting,
            weather=weather,
            lighting=lighting,
            atmosphere=atmosphere,
            architecture_style=architecture_style,
            color_palette=color_palette,
            scene_rules=scene_rules,
            prompt_hint=prompt_hint,
            llm_summary=llm_summary,
            image_prompt_base=image_prompt_base,
            refine_prompt=refine_prompt,
            has_base_image=bool(base_path and base_path.exists()),
        )

        if base_path and base_path.exists():
            result = await asyncio.to_thread(
                self.nanobanana.generate_image_to_image,
                str(base_path),
                prompt,
                "16:9",
                "2k",
            )
            source = "nanobanana-scene-refine"
        else:
            result = await asyncio.to_thread(
                self.nanobanana.generate_text_to_image,
                prompt,
                "16:9",
                "2k",
            )
            source = "nanobanana-scene-prototype"

        if not result.get("success"):
            raise RuntimeError(result.get("error") or "NanoBanana 场景图生成失败")

        image_data = result.get("image_data")
        if not image_data:
            raise RuntimeError("NanoBanana 未返回场景图片数据")

        asset_id = uuid.uuid4().hex
        safe_name = f"{asset_id}_scene.png"
        output_path = self.prototype_root / safe_name
        output_path.write_bytes(image_data)

        return {
            "asset_url": self._build_asset_url(output_path),
            "asset_type": "image/png",
            "asset_filename": safe_name,
            "prompt": prompt,
            "source": source,
            "status": "completed",
            "notes": "用户可见场景原型图，可继续微调后保存。",
        }

    def merge_profiles(
        self,
        *,
        selected_profiles: List[Dict[str, Any]],
        direct_profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for index, profile in enumerate([*selected_profiles, *direct_profiles]):
            normalized = self.normalize_profile(profile, index)
            profile_key = normalized["id"] or normalized["name"]
            if profile_key and profile_key not in seen:
                merged.append(normalized)
                seen.add(profile_key)

        return merged

    def normalize_profile(self, profile: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        return {
            "id": str(profile.get("id") or "").strip(),
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
            "tags": self._normalize_tags(profile.get("tags") or []),
            "allowed_characters": self._normalize_list_field(profile.get("allowed_characters") or []),
            "props_must_have": self._normalize_list_field(profile.get("props_must_have") or []),
            "props_forbidden": self._normalize_list_field(profile.get("props_forbidden") or []),
            "must_have_elements": self._normalize_list_field(profile.get("must_have_elements") or []),
            "forbidden_elements": self._normalize_list_field(profile.get("forbidden_elements") or []),
            "camera_preferences": self._normalize_list_field(profile.get("camera_preferences") or []),
            "profile_version": self._normalize_profile_version(profile.get("profile_version")),
            "source": str(profile.get("source") or "library").strip() or "library",
            "reference_image_url": str(profile.get("reference_image_url") or "").strip(),
            "reference_image_original_name": str(profile.get("reference_image_original_name") or "").strip(),
            "created_at": str(profile.get("created_at") or now),
            "updated_at": str(profile.get("updated_at") or profile.get("created_at") or now),
        }

    def _build_scene_image_prompt(
        self,
        *,
        name: str,
        scene_type: str,
        description: str,
        story_function: str,
        location: str,
        time_setting: str,
        weather: str,
        lighting: str,
        atmosphere: str,
        architecture_style: str,
        color_palette: str,
        scene_rules: str,
        prompt_hint: str,
        llm_summary: str,
        image_prompt_base: str,
        refine_prompt: str,
        has_base_image: bool,
    ) -> str:
        subject = name.strip() or "the scene"
        base_parts = [
            f"Scene: {subject}.",
            f"Type: {scene_type.strip()}." if scene_type.strip() else "",
            f"Function in story: {story_function.strip()}." if story_function.strip() else "",
            f"Location: {location.strip()}." if location.strip() else "",
            f"Summary: {llm_summary.strip()}." if llm_summary.strip() else "",
            f"Description: {description.strip()}." if description.strip() else "",
            f"Time: {time_setting.strip()}." if time_setting.strip() else "",
            f"Weather: {weather.strip()}." if weather.strip() else "",
            f"Lighting: {lighting.strip()}." if lighting.strip() else "",
            f"Atmosphere: {atmosphere.strip()}." if atmosphere.strip() else "",
            f"Architecture: {architecture_style.strip()}." if architecture_style.strip() else "",
            f"Color palette: {color_palette.strip()}." if color_palette.strip() else "",
            f"Rules: {scene_rules.strip()}." if scene_rules.strip() else "",
            f"Stable image prompt base: {image_prompt_base.strip()}." if image_prompt_base.strip() else "",
            f"Extra constraints: {prompt_hint.strip()}." if prompt_hint.strip() else "",
            f"User refinement request: {refine_prompt.strip()}." if refine_prompt.strip() else "",
        ]
        if has_base_image:
            base_parts.append(
                "Use the input image as the base scene reference. Preserve the core layout, spatial logic, atmosphere, lighting direction, and recognizable set dressing while improving quality and coherence."
            )
        else:
            base_parts.append(
                "Create a polished scene concept image for user review. No collage, strong environmental storytelling, production-ready cinematic composition."
            )
        base_parts.append(
            "Cute or realistic tone should follow the scene description. Keep composition readable, lighting coherent, textures clean, no watermark, no text overlay."
        )
        return " ".join(part for part in base_parts if part).strip()

    def _build_asset_url(self, output_path: Path) -> str:
        relative_path = output_path.relative_to(Path(settings.UPLOAD_DIR))
        return f"/uploads/{relative_path.as_posix()}"

    def _asset_url_to_path(self, asset_url: str) -> Optional[Path]:
        if not asset_url:
            return None
        if asset_url.startswith("/uploads/"):
            return Path(settings.UPLOAD_DIR) / asset_url.replace("/uploads/", "", 1)
        return None

    def _asset_url_to_db_path(self, asset_url: str) -> Optional[str]:
        asset_path = self._asset_url_to_path(asset_url)
        return str(asset_path) if asset_path else None

    def _delete_local_asset(self, asset_path: Optional[str]) -> None:
        if not asset_path:
            return
        try:
            path = Path(asset_path)
            if path.exists() and path.is_file():
                path.unlink()
        except Exception:
            return

    def _normalize_tags(self, tags: Any) -> List[str]:
        if isinstance(tags, str):
            items = tags.replace("，", ",").split(",")
        else:
            items = list(tags)
        return [str(item).strip() for item in items if str(item).strip()]

    def _normalize_list_field(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = str(value).replace("，", ",").replace("\n", ",").split(",")
        else:
            items = list(value)
        return [str(item).strip() for item in items if str(item).strip()]

    def _normalize_profile_version(self, value: Any) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            normalized = 1
        return normalized if normalized > 0 else 1

    def _guess_suffix(self, filename: str, content_type: str) -> str:
        source = filename or ""
        ext = Path(source).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".webp"}:
            return ".jpg" if ext == ".jpeg" else ext
        if content_type == "image/png":
            return ".png"
        if content_type == "image/webp":
            return ".webp"
        return ".jpg"


pipeline_scene_library_service = PipelineSceneLibraryService()
