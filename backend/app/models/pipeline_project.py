from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from app.models.base import BaseModel


class PipelineProject(BaseModel):
    __tablename__ = "pipeline_projects"

    id = Column(String(50), primary_key=True, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    project_title = Column(String(255), nullable=False, default="未命名项目")
    current_step = Column(Integer, nullable=False, default=0)
    state = Column(JSON, nullable=False)
    status = Column(String(50), nullable=False, default="draft")
    last_render_task_id = Column(String(100), nullable=True)
    summary = Column(Text, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "project_title": self.project_title or "未命名项目",
            "current_step": int(self.current_step or 0),
            "state": self.state or {},
            "status": self.status or "draft",
            "last_render_task_id": self.last_render_task_id or "",
            "summary": self.summary or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
