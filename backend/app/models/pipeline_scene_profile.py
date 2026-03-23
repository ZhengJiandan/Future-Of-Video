from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from app.models.base import BaseModel
from app.utils.image_variants import thumbnail_url_for_asset


class PipelineSceneProfile(BaseModel):
    """主链路使用的通用场景档案模型。"""

    __tablename__ = "pipeline_scene_profiles"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    category = Column(String(100), nullable=True, index=True)
    scene_type = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    story_function = Column(String(100), nullable=True)
    location = Column(String(255), nullable=True)
    scene_rules = Column(Text, nullable=True)
    time_setting = Column(String(100), nullable=True)
    weather = Column(String(100), nullable=True)
    lighting = Column(String(100), nullable=True)
    atmosphere = Column(Text, nullable=True)
    architecture_style = Column(Text, nullable=True)
    color_palette = Column(Text, nullable=True)
    prompt_hint = Column(Text, nullable=True)
    llm_summary = Column(Text, nullable=True)
    image_prompt_base = Column(Text, nullable=True)
    video_prompt_base = Column(Text, nullable=True)
    negative_prompt = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    allowed_characters = Column(JSON, nullable=True)
    props_must_have = Column(JSON, nullable=True)
    props_forbidden = Column(JSON, nullable=True)
    must_have_elements = Column(JSON, nullable=True)
    forbidden_elements = Column(JSON, nullable=True)
    camera_preferences = Column(JSON, nullable=True)
    profile_version = Column(Integer, nullable=False, default=1)
    source = Column(String(50), nullable=False, default="library")

    reference_image_url = Column(String(500), nullable=True)
    reference_image_path = Column(String(500), nullable=True)
    reference_image_original_name = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        reference_image_thumbnail_url = thumbnail_url_for_asset(self.reference_image_url or "")
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category or "",
            "scene_type": self.scene_type or "",
            "description": self.description or "",
            "story_function": self.story_function or "",
            "location": self.location or "",
            "scene_rules": self.scene_rules or "",
            "time_setting": self.time_setting or "",
            "weather": self.weather or "",
            "lighting": self.lighting or "",
            "atmosphere": self.atmosphere or "",
            "architecture_style": self.architecture_style or "",
            "color_palette": self.color_palette or "",
            "prompt_hint": self.prompt_hint or "",
            "llm_summary": self.llm_summary or "",
            "image_prompt_base": self.image_prompt_base or "",
            "video_prompt_base": self.video_prompt_base or "",
            "negative_prompt": self.negative_prompt or "",
            "tags": self.tags or [],
            "allowed_characters": self.allowed_characters or [],
            "props_must_have": self.props_must_have or [],
            "props_forbidden": self.props_forbidden or [],
            "must_have_elements": self.must_have_elements or [],
            "forbidden_elements": self.forbidden_elements or [],
            "camera_preferences": self.camera_preferences or [],
            "profile_version": self.profile_version or 1,
            "source": self.source or "library",
            "reference_image_url": self.reference_image_url or "",
            "reference_image_thumbnail_url": reference_image_thumbnail_url,
            "reference_image_original_name": self.reference_image_original_name or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
