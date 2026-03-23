#!/usr/bin/env python3
"""数据库持久化的主链路角色档案服务。"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.pipeline_character_profile import PipelineCharacterProfile
from app.services.preferred_image_generation import PreferredImageGenerationClient
from app.utils.image_variants import (
    build_upload_url,
    ensure_thumbnail_for_path,
    thumbnail_path_for_source_path,
    thumbnail_url_for_asset,
)

logger = logging.getLogger(__name__)


class PipelineCharacterLibraryService:
    def __init__(self) -> None:
        self.library_root = Path(settings.UPLOAD_DIR) / "generated" / "pipeline" / "character_library"
        self.reference_root = self.library_root / "references"
        self.prototype_root = self.library_root / "prototypes"
        self.three_view_root = self.library_root / "three_views"
        self.face_closeup_root = self.library_root / "face_closeups"
        self.reference_root.mkdir(parents=True, exist_ok=True)
        self.prototype_root.mkdir(parents=True, exist_ok=True)
        self.three_view_root.mkdir(parents=True, exist_ok=True)
        self.face_closeup_root.mkdir(parents=True, exist_ok=True)
        self.image_generator = PreferredImageGenerationClient()

    async def list_profiles(self, db: AsyncSession) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineCharacterProfile).order_by(
                PipelineCharacterProfile.updated_at.desc(),
                PipelineCharacterProfile.created_at.desc(),
            )
        )
        profiles = result.scalars().all()
        await self._backfill_missing_face_closeups(db, profiles)
        return [item.to_dict() for item in profiles]

    async def get_profile_by_id(self, db: AsyncSession, profile_id: str) -> Optional[Dict[str, Any]]:
        normalized_id = str(profile_id or "").strip()
        if not normalized_id:
            return None

        result = await db.execute(
            select(PipelineCharacterProfile).where(PipelineCharacterProfile.id == normalized_id)
        )
        profile = result.scalar_one_or_none()
        if profile:
            await self._backfill_missing_face_closeups(db, [profile])
        return profile.to_dict() if profile else None

    async def get_profiles_by_ids(self, db: AsyncSession, profile_ids: List[str]) -> List[Dict[str, Any]]:
        normalized_ids = [str(item).strip() for item in profile_ids if str(item).strip()]
        if not normalized_ids:
            return []

        result = await db.execute(
            select(PipelineCharacterProfile).where(PipelineCharacterProfile.id.in_(normalized_ids))
        )
        profiles = result.scalars().all()
        await self._backfill_missing_face_closeups(db, profiles)
        lookup = {item.id: item.to_dict() for item in profiles}
        return [lookup[profile_id] for profile_id in normalized_ids if profile_id in lookup]

    async def create_profile(self, db: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("角色名称不能为空")

        auto_generate_identity_assets = payload.get("auto_generate_identity_assets", True) is not False
        final_reference_image_url = str(payload.get("reference_image_url") or "").strip()
        generated_three_view_url = str(payload.get("three_view_image_url") or "").strip()
        generated_three_view_prompt = str(payload.get("three_view_prompt") or "").strip()
        generated_face_closeup_url = str(payload.get("face_closeup_image_url") or "").strip()
        if auto_generate_identity_assets and final_reference_image_url and not generated_three_view_url:
            try:
                generated_three_view = await self.generate_three_view_asset(
                    reference_image_url=final_reference_image_url,
                    name=name,
                    role=str(payload.get("role") or "").strip(),
                    description=str(payload.get("description") or "").strip(),
                    appearance=str(payload.get("appearance") or "").strip(),
                    personality=str(payload.get("personality") or "").strip(),
                    prompt_hint=str(payload.get("prompt_hint") or "").strip(),
                )
                generated_three_view_url = str(generated_three_view.get("asset_url") or "").strip()
                generated_three_view_prompt = str(generated_three_view.get("prompt") or "").strip()
            except Exception:
                generated_three_view_url = ""
                generated_three_view_prompt = ""

        if auto_generate_identity_assets and final_reference_image_url and not generated_face_closeup_url:
            try:
                generated_face_closeup_url = await asyncio.to_thread(
                    self._generate_face_closeup_asset,
                    final_reference_image_url,
                )
            except Exception:
                logger.warning(
                    "Generate face closeup failed during character create: name=%s reference=%s",
                    name,
                    final_reference_image_url,
                    exc_info=True,
                )
                generated_face_closeup_url = ""

        now = datetime.utcnow()
        profile = PipelineCharacterProfile(
            id=uuid.uuid4().hex,
            name=name,
            category=str(payload.get("category") or "").strip(),
            role=str(payload.get("role") or "").strip(),
            archetype=str(payload.get("archetype") or "").strip(),
            age_range=str(payload.get("age_range") or "").strip(),
            gender_presentation=str(payload.get("gender_presentation") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            appearance=str(payload.get("appearance") or "").strip(),
            personality=str(payload.get("personality") or "").strip(),
            core_appearance=str(payload.get("core_appearance") or "").strip(),
            hair=str(payload.get("hair") or "").strip(),
            face_features=str(payload.get("face_features") or "").strip(),
            body_shape=str(payload.get("body_shape") or "").strip(),
            outfit=str(payload.get("outfit") or "").strip(),
            gear=str(payload.get("gear") or "").strip(),
            color_palette=str(payload.get("color_palette") or "").strip(),
            visual_do_not_change=str(payload.get("visual_do_not_change") or "").strip(),
            speaking_style=str(payload.get("speaking_style") or "").strip(),
            common_actions=str(payload.get("common_actions") or "").strip(),
            emotion_baseline=str(payload.get("emotion_baseline") or "").strip(),
            voice_description=str(payload.get("voice_description") or "").strip(),
            forbidden_behaviors=str(payload.get("forbidden_behaviors") or "").strip(),
            prompt_hint=str(payload.get("prompt_hint") or "").strip(),
            llm_summary=str(payload.get("llm_summary") or "").strip(),
            image_prompt_base=str(payload.get("image_prompt_base") or "").strip(),
            video_prompt_base=str(payload.get("video_prompt_base") or "").strip(),
            negative_prompt=str(payload.get("negative_prompt") or "").strip(),
            tags=self._normalize_tags(payload.get("tags") or []),
            must_keep=self._normalize_list_field(payload.get("must_keep") or []),
            forbidden_traits=self._normalize_list_field(payload.get("forbidden_traits") or []),
            aliases=self._normalize_list_field(payload.get("aliases") or []),
            profile_version=self._normalize_profile_version(payload.get("profile_version")),
            source=str(payload.get("source") or "library").strip() or "library",
            reference_image_url=final_reference_image_url or None,
            reference_image_path=self._asset_url_to_db_path(final_reference_image_url),
            reference_image_original_name=str(payload.get("reference_image_original_name") or "").strip() or None,
            three_view_image_url=generated_three_view_url or None,
            three_view_image_path=self._asset_url_to_db_path(generated_three_view_url),
            three_view_prompt=generated_three_view_prompt or None,
            face_closeup_image_url=generated_face_closeup_url or None,
            face_closeup_image_path=self._asset_url_to_db_path(generated_face_closeup_url),
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
            raise ValueError("角色档案不存在")

        result = await db.execute(
            select(PipelineCharacterProfile).where(PipelineCharacterProfile.id == normalized_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return None

        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("角色名称不能为空")

        original_reference_image_url = profile.reference_image_url or ""
        original_reference_image_path = profile.reference_image_path or ""
        original_three_view_image_path = profile.three_view_image_path or ""
        original_face_closeup_image_path = profile.face_closeup_image_path or ""

        auto_generate_identity_assets = payload.get("auto_generate_identity_assets", True) is not False
        final_reference_image_url = str(payload.get("reference_image_url") or "").strip()
        generated_three_view_url = str(payload.get("three_view_image_url") or "").strip()
        generated_three_view_prompt = str(payload.get("three_view_prompt") or "").strip()
        generated_face_closeup_url = str(payload.get("face_closeup_image_url") or "").strip()

        reference_image_changed = final_reference_image_url != original_reference_image_url

        if (
            auto_generate_identity_assets
            and final_reference_image_url
            and (reference_image_changed or not (profile.three_view_image_url or "").strip())
        ):
            try:
                generated_three_view = await self.generate_three_view_asset(
                    reference_image_url=final_reference_image_url,
                    name=name,
                    role=str(payload.get("role") or "").strip(),
                    description=str(payload.get("description") or "").strip(),
                    appearance=str(payload.get("appearance") or "").strip(),
                    personality=str(payload.get("personality") or "").strip(),
                    prompt_hint=str(payload.get("prompt_hint") or "").strip(),
                )
                generated_three_view_url = str(generated_three_view.get("asset_url") or "").strip()
                generated_three_view_prompt = str(generated_three_view.get("prompt") or "").strip()
            except Exception:
                generated_three_view_url = profile.three_view_image_url or ""
                generated_three_view_prompt = profile.three_view_prompt or ""
        elif not final_reference_image_url:
            generated_three_view_url = ""
            generated_three_view_prompt = ""
        else:
            generated_three_view_url = generated_three_view_url or (profile.three_view_image_url or "")
            generated_three_view_prompt = generated_three_view_prompt or (profile.three_view_prompt or "")

        if auto_generate_identity_assets and final_reference_image_url and (
            reference_image_changed or not (profile.face_closeup_image_url or "").strip()
        ):
            try:
                generated_face_closeup_url = await asyncio.to_thread(
                    self._generate_face_closeup_asset,
                    final_reference_image_url,
                )
            except Exception:
                logger.warning(
                    "Generate face closeup failed during character update: profile_id=%s name=%s reference=%s",
                    profile.id,
                    name,
                    final_reference_image_url,
                    exc_info=True,
                )
                generated_face_closeup_url = profile.face_closeup_image_url or ""
        elif not final_reference_image_url:
            generated_face_closeup_url = ""
        else:
            generated_face_closeup_url = generated_face_closeup_url or (profile.face_closeup_image_url or "")

        profile.name = name
        profile.category = str(payload.get("category") or "").strip()
        profile.role = str(payload.get("role") or "").strip()
        profile.archetype = str(payload.get("archetype") or "").strip()
        profile.age_range = str(payload.get("age_range") or "").strip()
        profile.gender_presentation = str(payload.get("gender_presentation") or "").strip()
        profile.description = str(payload.get("description") or "").strip()
        profile.appearance = str(payload.get("appearance") or "").strip()
        profile.personality = str(payload.get("personality") or "").strip()
        profile.core_appearance = str(payload.get("core_appearance") or "").strip()
        profile.hair = str(payload.get("hair") or "").strip()
        profile.face_features = str(payload.get("face_features") or "").strip()
        profile.body_shape = str(payload.get("body_shape") or "").strip()
        profile.outfit = str(payload.get("outfit") or "").strip()
        profile.gear = str(payload.get("gear") or "").strip()
        profile.color_palette = str(payload.get("color_palette") or "").strip()
        profile.visual_do_not_change = str(payload.get("visual_do_not_change") or "").strip()
        profile.speaking_style = str(payload.get("speaking_style") or "").strip()
        profile.common_actions = str(payload.get("common_actions") or "").strip()
        profile.emotion_baseline = str(payload.get("emotion_baseline") or "").strip()
        profile.voice_description = str(payload.get("voice_description") or "").strip()
        profile.forbidden_behaviors = str(payload.get("forbidden_behaviors") or "").strip()
        profile.prompt_hint = str(payload.get("prompt_hint") or "").strip()
        profile.llm_summary = str(payload.get("llm_summary") or "").strip()
        profile.image_prompt_base = str(payload.get("image_prompt_base") or "").strip()
        profile.video_prompt_base = str(payload.get("video_prompt_base") or "").strip()
        profile.negative_prompt = str(payload.get("negative_prompt") or "").strip()
        profile.tags = self._normalize_tags(payload.get("tags") or [])
        profile.must_keep = self._normalize_list_field(payload.get("must_keep") or [])
        profile.forbidden_traits = self._normalize_list_field(payload.get("forbidden_traits") or [])
        profile.aliases = self._normalize_list_field(payload.get("aliases") or [])
        profile.profile_version = self._normalize_profile_version(payload.get("profile_version"))
        profile.source = str(payload.get("source") or "library").strip() or "library"
        profile.reference_image_url = final_reference_image_url or None
        profile.reference_image_path = self._asset_url_to_db_path(final_reference_image_url)
        profile.reference_image_original_name = (
            str(payload.get("reference_image_original_name") or "").strip() or None
        )
        profile.three_view_image_url = generated_three_view_url or None
        profile.three_view_image_path = self._asset_url_to_db_path(generated_three_view_url)
        profile.three_view_prompt = generated_three_view_prompt or None
        profile.face_closeup_image_url = generated_face_closeup_url or None
        profile.face_closeup_image_path = self._asset_url_to_db_path(generated_face_closeup_url)
        profile.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(profile)

        if reference_image_changed and original_reference_image_path and original_reference_image_path != profile.reference_image_path:
            self._delete_local_asset(original_reference_image_path)
        if original_three_view_image_path and original_three_view_image_path != profile.three_view_image_path:
            self._delete_local_asset(original_three_view_image_path)
        if original_face_closeup_image_path and original_face_closeup_image_path != profile.face_closeup_image_path:
            self._delete_local_asset(original_face_closeup_image_path)

        return profile.to_dict()

    async def delete_profile(self, db: AsyncSession, profile_id: str) -> bool:
        result = await db.execute(
            select(PipelineCharacterProfile).where(PipelineCharacterProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return False

        self._delete_local_asset(profile.reference_image_path)
        self._delete_local_asset(profile.three_view_image_path)
        self._delete_local_asset(profile.face_closeup_image_path)

        await db.execute(delete(PipelineCharacterProfile).where(PipelineCharacterProfile.id == profile_id))
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
        safe_name = f"{asset_id}_reference{suffix}"
        output_path = self.reference_root / safe_name
        output_path.write_bytes(content)
        thumbnail_path = ensure_thumbnail_for_path(output_path)
        return {
            "id": asset_id,
            "url": self._build_asset_url(output_path),
            "thumbnail_url": build_upload_url(thumbnail_path) if thumbnail_path else "",
            "filename": safe_name,
            "original_filename": filename,
            "content_type": content_type,
            "size": len(content),
            "source": "character-reference-upload",
        }

    async def generate_three_view_asset(
        self,
        *,
        reference_image_url: str,
        name: str = "",
        role: str = "",
        description: str = "",
        appearance: str = "",
        personality: str = "",
        prompt_hint: str = "",
    ) -> Dict[str, Any]:
        reference_path = self._asset_url_to_path(reference_image_url)
        if not reference_path or not reference_path.exists():
            raise ValueError("参考图不存在，请重新上传")

        prompt = self._build_three_view_prompt(
            name=name,
            role=role,
            description=description,
            appearance=appearance,
            personality=personality,
            prompt_hint=prompt_hint,
        )

        result = await asyncio.to_thread(
            self.image_generator.generate_image_to_image,
            str(reference_path),
            prompt,
            "16:9",
            "2k",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "角色三视图生成失败")

        image_data = result.get("image_data")
        if not image_data:
            raise RuntimeError("图片生成服务未返回三视图图片数据")

        asset_id = uuid.uuid4().hex
        safe_name = f"{asset_id}_three_view.png"
        output_path = self.three_view_root / safe_name
        output_path.write_bytes(image_data)
        thumbnail_path = ensure_thumbnail_for_path(output_path)

        return {
            "asset_url": self._build_asset_url(output_path),
            "thumbnail_url": build_upload_url(thumbnail_path) if thumbnail_path else "",
            "asset_type": "image/png",
            "asset_filename": safe_name,
            "prompt": prompt,
            "source": str(result.get("source") or "image-provider-three-view"),
            "status": "completed",
            "notes": "单张画布三视图：正面、侧面、背面。",
        }

    async def generate_character_image_asset(
        self,
        *,
        base_image_url: str = "",
        name: str = "",
        role: str = "",
        description: str = "",
        appearance: str = "",
        personality: str = "",
        prompt_hint: str = "",
        llm_summary: str = "",
        image_prompt_base: str = "",
        refine_prompt: str = "",
    ) -> Dict[str, Any]:
        base_path = self._asset_url_to_path(base_image_url)
        prompt = self._build_character_image_prompt(
            name=name,
            role=role,
            description=description,
            appearance=appearance,
            personality=personality,
            prompt_hint=prompt_hint,
            llm_summary=llm_summary,
            image_prompt_base=image_prompt_base,
            refine_prompt=refine_prompt,
            has_base_image=bool(base_path and base_path.exists()),
        )

        if base_path and base_path.exists():
            result = await asyncio.to_thread(
                self.image_generator.generate_image_to_image,
                str(base_path),
                prompt,
                "16:9",
                "2k",
            )
        else:
            result = await asyncio.to_thread(
                self.image_generator.generate_text_to_image,
                prompt,
                "16:9",
                "2k",
            )

        if not result.get("success"):
            raise RuntimeError(result.get("error") or "角色图生成失败")

        image_data = result.get("image_data")
        if not image_data:
            raise RuntimeError("图片生成服务未返回角色图片数据")

        asset_id = uuid.uuid4().hex
        safe_name = f"{asset_id}_character.png"
        output_path = self.prototype_root / safe_name
        output_path.write_bytes(image_data)
        thumbnail_path = ensure_thumbnail_for_path(output_path)

        return {
            "asset_url": self._build_asset_url(output_path),
            "thumbnail_url": build_upload_url(thumbnail_path) if thumbnail_path else "",
            "asset_type": "image/png",
            "asset_filename": safe_name,
            "prompt": prompt,
            "source": str(result.get("source") or "image-provider-character"),
            "status": "completed",
            "notes": "用户可见角色原型图，可继续微调后保存。",
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
            "voice_description": str(profile.get("voice_description") or "").strip(),
            "forbidden_behaviors": str(profile.get("forbidden_behaviors") or "").strip(),
            "prompt_hint": str(profile.get("prompt_hint") or "").strip(),
            "llm_summary": str(profile.get("llm_summary") or "").strip(),
            "image_prompt_base": str(profile.get("image_prompt_base") or "").strip(),
            "video_prompt_base": str(profile.get("video_prompt_base") or "").strip(),
            "negative_prompt": str(profile.get("negative_prompt") or "").strip(),
            "tags": self._normalize_tags(profile.get("tags") or []),
            "must_keep": self._normalize_list_field(profile.get("must_keep") or []),
            "forbidden_traits": self._normalize_list_field(profile.get("forbidden_traits") or []),
            "aliases": self._normalize_list_field(profile.get("aliases") or []),
            "profile_version": self._normalize_profile_version(profile.get("profile_version")),
            "source": str(profile.get("source") or "library").strip() or "library",
            "reference_image_url": str(profile.get("reference_image_url") or "").strip(),
            "reference_image_thumbnail_url": str(
                profile.get("reference_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("reference_image_url") or "").strip())
                or ""
            ).strip(),
            "reference_image_original_name": str(profile.get("reference_image_original_name") or "").strip(),
            "three_view_image_url": str(profile.get("three_view_image_url") or "").strip(),
            "three_view_image_thumbnail_url": str(
                profile.get("three_view_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("three_view_image_url") or "").strip())
                or ""
            ).strip(),
            "three_view_prompt": str(profile.get("three_view_prompt") or "").strip(),
            "face_closeup_image_url": str(profile.get("face_closeup_image_url") or "").strip(),
            "face_closeup_image_thumbnail_url": str(
                profile.get("face_closeup_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("face_closeup_image_url") or "").strip())
                or ""
            ).strip(),
            "display_image_url": str(profile.get("display_image_url") or profile.get("reference_image_url") or "").strip(),
            "display_image_thumbnail_url": str(
                profile.get("display_image_thumbnail_url")
                or profile.get("reference_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("display_image_url") or profile.get("reference_image_url") or "").strip())
                or ""
            ).strip(),
            "identity_reference_images": self._build_identity_reference_images(profile),
            "identity_anchor_pack": self._build_identity_anchor_pack(profile),
            "created_at": str(profile.get("created_at") or now),
            "updated_at": str(profile.get("updated_at") or profile.get("created_at") or now),
        }

    def _build_identity_reference_images(self, profile: Dict[str, Any]) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        main_reference = str(profile.get("reference_image_url") or "").strip()
        three_view = str(profile.get("three_view_image_url") or "").strip()
        face_closeup = str(profile.get("face_closeup_image_url") or "").strip()
        if main_reference:
            items.append(
                {
                    "type": "main_reference",
                    "label": "主参考图",
                    "url": main_reference,
                    "thumbnail_url": thumbnail_url_for_asset(main_reference),
                }
            )
        if three_view:
            items.append(
                {
                    "type": "three_view",
                    "label": "三视图",
                    "url": three_view,
                    "thumbnail_url": thumbnail_url_for_asset(three_view),
                }
            )
        if face_closeup:
            items.append(
                {
                    "type": "face_closeup",
                    "label": "面部特写",
                    "url": face_closeup,
                    "thumbnail_url": thumbnail_url_for_asset(face_closeup),
                }
            )
        return items

    def _build_identity_anchor_pack(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "character_id": str(profile.get("id") or "").strip(),
            "profile_version": self._normalize_profile_version(profile.get("profile_version")),
            "display_image_url": str(profile.get("reference_image_url") or "").strip(),
            "display_image_thumbnail_url": str(
                profile.get("display_image_thumbnail_url")
                or profile.get("reference_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("reference_image_url") or "").strip())
                or ""
            ).strip(),
            "three_view_image_url": str(profile.get("three_view_image_url") or "").strip(),
            "three_view_image_thumbnail_url": str(
                profile.get("three_view_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("three_view_image_url") or "").strip())
                or ""
            ).strip(),
            "face_closeup_image_url": str(profile.get("face_closeup_image_url") or "").strip(),
            "face_closeup_image_thumbnail_url": str(
                profile.get("face_closeup_image_thumbnail_url")
                or thumbnail_url_for_asset(str(profile.get("face_closeup_image_url") or "").strip())
                or ""
            ).strip(),
            "must_keep": self._normalize_list_field(profile.get("must_keep") or []),
            "forbidden_traits": self._normalize_list_field(profile.get("forbidden_traits") or []),
            "core_appearance": str(profile.get("core_appearance") or "").strip(),
            "outfit": str(profile.get("outfit") or "").strip(),
            "color_palette": str(profile.get("color_palette") or "").strip(),
            "speaking_style": str(profile.get("speaking_style") or "").strip(),
            "voice_description": str(profile.get("voice_description") or "").strip(),
            "common_actions": str(profile.get("common_actions") or "").strip(),
            "llm_summary": str(profile.get("llm_summary") or "").strip(),
            "image_prompt_base": str(profile.get("image_prompt_base") or "").strip(),
            "video_prompt_base": str(profile.get("video_prompt_base") or "").strip(),
        }

    def _build_three_view_prompt(
        self,
        *,
        name: str,
        role: str,
        description: str,
        appearance: str,
        personality: str,
        prompt_hint: str,
    ) -> str:
        subject = name.strip() or "the same character"
        role_text = f"Role: {role.strip()}. " if role.strip() else ""
        description_text = f"Description: {description.strip()}. " if description.strip() else ""
        appearance_text = f"Appearance: {appearance.strip()}. " if appearance.strip() else ""
        personality_text = f"Personality cues: {personality.strip()}. " if personality.strip() else ""
        prompt_hint_text = f"Extra constraints: {prompt_hint.strip()}. " if prompt_hint.strip() else ""
        return (
            f"Use the input image as the core identity reference for {subject}. "
            f"{role_text}{description_text}{appearance_text}{personality_text}{prompt_hint_text}"
            "Create a single professional character turnaround sheet on one canvas. "
            "Show the same character in three full-body views: front view, left side view, and back view. "
            "Keep face, hairstyle, costume, silhouette, body proportions, gear details, and colors fully consistent. "
            "Neutral standing pose, arms relaxed, clean studio background, no extra characters, no collage clutter, "
            "high detail, production-ready concept art sheet."
        ).strip()

    def _build_character_image_prompt(
        self,
        *,
        name: str,
        role: str,
        description: str,
        appearance: str,
        personality: str,
        prompt_hint: str,
        llm_summary: str,
        image_prompt_base: str,
        refine_prompt: str,
        has_base_image: bool,
    ) -> str:
        subject = name.strip() or "the character"
        base_parts = [
            f"Character: {subject}.",
            f"Role: {role.strip()}." if role.strip() else "",
            f"Summary: {llm_summary.strip()}." if llm_summary.strip() else "",
            f"Description: {description.strip()}." if description.strip() else "",
            f"Appearance: {appearance.strip()}." if appearance.strip() else "",
            f"Personality cues: {personality.strip()}." if personality.strip() else "",
            f"Stable image prompt base: {image_prompt_base.strip()}." if image_prompt_base.strip() else "",
            f"Extra constraints: {prompt_hint.strip()}." if prompt_hint.strip() else "",
            f"User refinement request: {refine_prompt.strip()}." if refine_prompt.strip() else "",
        ]
        if has_base_image:
            base_parts.append(
                "Use the input image as the core identity reference. Preserve facial identity, hairstyle, body proportion, costume logic, and recognizable silhouette while refining quality and design."
            )
        else:
            base_parts.append(
                "Create a polished single-character concept portrait for user review. One character only, clean composition, production-ready, visually distinctive, high detail."
            )
        base_parts.append(
            "Cinematic concept art, coherent lighting, clean anatomy, no collage, no extra characters, no text, no watermark."
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
            thumbnail_path = thumbnail_path_for_source_path(path)
            if thumbnail_path.exists() and thumbnail_path.is_file():
                thumbnail_path.unlink()
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
            items = re.split(r"[\n,，]", value)
        else:
            items = list(value)
        return [str(item).strip() for item in items if str(item).strip()]

    def _normalize_profile_version(self, value: Any) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            normalized = 1
        return normalized if normalized > 0 else 1

    async def _backfill_missing_face_closeups(
        self,
        db: AsyncSession,
        profiles: List[PipelineCharacterProfile],
    ) -> None:
        missing_profiles = [
            profile
            for profile in profiles
            if (profile.reference_image_url or "").strip() and not (profile.face_closeup_image_url or "").strip()
        ]
        if not missing_profiles:
            return

        updated = False
        for profile in missing_profiles:
            try:
                generated_face_closeup_url = await asyncio.to_thread(
                    self._generate_face_closeup_asset,
                    str(profile.reference_image_url or "").strip(),
                )
            except Exception:
                logger.warning(
                    "Backfill face closeup failed: profile_id=%s name=%s reference=%s",
                    profile.id,
                    profile.name,
                    profile.reference_image_url,
                    exc_info=True,
                )
                continue

            if not generated_face_closeup_url:
                continue

            profile.face_closeup_image_url = generated_face_closeup_url
            profile.face_closeup_image_path = self._asset_url_to_db_path(generated_face_closeup_url)
            profile.updated_at = datetime.utcnow()
            updated = True

        if updated:
            await db.commit()

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

    def _generate_face_closeup_asset(self, reference_image_url: str) -> str:
        reference_path = self._asset_url_to_path(reference_image_url)
        if not reference_path or not reference_path.exists():
            raise ValueError("参考图不存在，无法生成面部特写")

        asset_id = uuid.uuid4().hex
        output_path = self.face_closeup_root / f"{asset_id}_face_closeup.png"

        with Image.open(reference_path) as image:
            prepared = image.convert("RGB")
            width, height = prepared.size
            crop_size = max(64, int(min(width, height) * 0.56))
            crop_size = min(crop_size, width, height)

            center_x = width / 2
            center_y = height * 0.3
            left = int(max(0, min(width - crop_size, center_x - crop_size / 2)))
            top = int(max(0, min(height - crop_size, center_y - crop_size / 2)))
            right = left + crop_size
            bottom = top + crop_size

            closeup = prepared.crop((left, top, right, bottom)).resize((1024, 1024))
            closeup.save(output_path, format="PNG")

        ensure_thumbnail_for_path(output_path)

        return self._build_asset_url(output_path)


pipeline_character_library_service = PipelineCharacterLibraryService()
