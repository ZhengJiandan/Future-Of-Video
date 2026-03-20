from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, JSON, String, Text

from app.models.base import BaseModel


class PipelineRenderTask(BaseModel):
    __tablename__ = "pipeline_render_tasks"

    id = Column(String(50), primary_key=True, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    project_id = Column(String(50), nullable=True, index=True)
    project_title = Column(String(255), nullable=False, default="未命名项目")
    segments = Column(JSON, nullable=False)
    keyframes = Column(JSON, nullable=False)
    character_profiles = Column(JSON, nullable=False)
    scene_profiles = Column(JSON, nullable=False)
    render_config = Column(JSON, nullable=False)
    status = Column(String(50), nullable=False, default="queued", index=True)
    progress = Column(Float, nullable=False, default=0.0)
    current_step = Column(String(255), nullable=False, default="等待开始")
    renderer = Column(String(100), nullable=False, default="pending")
    clips = Column(JSON, nullable=False)
    final_output = Column(JSON, nullable=False)
    fallback_used = Column(Boolean, nullable=False, default=False)
    warnings = Column(JSON, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "task_id": self.id,
            "project_id": self.project_id or "",
            "project_title": self.project_title or "未命名项目",
            "status": self.status or "queued",
            "progress": round(float(self.progress or 0.0), 2),
            "current_step": self.current_step or "等待开始",
            "renderer": self.renderer or "pending",
            "clips": self.clips or [],
            "character_profiles": self.character_profiles or [],
            "scene_profiles": self.scene_profiles or [],
            "final_output": self.final_output or {},
            "fallback_used": bool(self.fallback_used),
            "warnings": self.warnings or [],
            "render_config": self.render_config or {},
            "error": self.error or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
