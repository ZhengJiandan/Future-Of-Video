from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from app.models.base import BaseModel


class PipelineCharacterProfile(BaseModel):
    """主链路使用的通用角色档案模型。"""

    __tablename__ = "pipeline_character_profiles"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    category = Column(String(100), nullable=True, index=True)
    role = Column(String(100), nullable=True)
    archetype = Column(String(100), nullable=True, index=True)
    age_range = Column(String(50), nullable=True)
    gender_presentation = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    appearance = Column(Text, nullable=True)
    personality = Column(Text, nullable=True)
    core_appearance = Column(Text, nullable=True)
    hair = Column(Text, nullable=True)
    face_features = Column(Text, nullable=True)
    body_shape = Column(Text, nullable=True)
    outfit = Column(Text, nullable=True)
    gear = Column(Text, nullable=True)
    color_palette = Column(Text, nullable=True)
    visual_do_not_change = Column(Text, nullable=True)
    speaking_style = Column(Text, nullable=True)
    common_actions = Column(Text, nullable=True)
    emotion_baseline = Column(Text, nullable=True)
    forbidden_behaviors = Column(Text, nullable=True)
    prompt_hint = Column(Text, nullable=True)
    llm_summary = Column(Text, nullable=True)
    image_prompt_base = Column(Text, nullable=True)
    video_prompt_base = Column(Text, nullable=True)
    negative_prompt = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    must_keep = Column(JSON, nullable=True)
    forbidden_traits = Column(JSON, nullable=True)
    aliases = Column(JSON, nullable=True)
    profile_version = Column(Integer, nullable=False, default=1)
    source = Column(String(50), nullable=False, default="library")

    reference_image_url = Column(String(500), nullable=True)
    reference_image_path = Column(String(500), nullable=True)
    reference_image_original_name = Column(String(255), nullable=True)

    three_view_image_url = Column(String(500), nullable=True)
    three_view_image_path = Column(String(500), nullable=True)
    three_view_prompt = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category or "",
            "role": self.role or "",
            "archetype": self.archetype or "",
            "age_range": self.age_range or "",
            "gender_presentation": self.gender_presentation or "",
            "description": self.description or "",
            "appearance": self.appearance or "",
            "personality": self.personality or "",
            "core_appearance": self.core_appearance or "",
            "hair": self.hair or "",
            "face_features": self.face_features or "",
            "body_shape": self.body_shape or "",
            "outfit": self.outfit or "",
            "gear": self.gear or "",
            "color_palette": self.color_palette or "",
            "visual_do_not_change": self.visual_do_not_change or "",
            "speaking_style": self.speaking_style or "",
            "common_actions": self.common_actions or "",
            "emotion_baseline": self.emotion_baseline or "",
            "forbidden_behaviors": self.forbidden_behaviors or "",
            "prompt_hint": self.prompt_hint or "",
            "llm_summary": self.llm_summary or "",
            "image_prompt_base": self.image_prompt_base or "",
            "video_prompt_base": self.video_prompt_base or "",
            "negative_prompt": self.negative_prompt or "",
            "tags": self.tags or [],
            "must_keep": self.must_keep or [],
            "forbidden_traits": self.forbidden_traits or [],
            "aliases": self.aliases or [],
            "profile_version": self.profile_version or 1,
            "source": self.source or "library",
            "reference_image_url": self.reference_image_url or "",
            "reference_image_original_name": self.reference_image_original_name or "",
            "three_view_image_url": self.three_view_image_url or "",
            "three_view_prompt": self.three_view_prompt or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
