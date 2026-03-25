from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_project import PipelineProject

logger = logging.getLogger(__name__)


class PipelineProjectService:
    async def list_projects(self, db: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(
                PipelineProject.id,
                PipelineProject.user_id,
                PipelineProject.project_title,
                PipelineProject.current_step,
                PipelineProject.status,
                PipelineProject.last_render_task_id,
                PipelineProject.summary,
                PipelineProject.created_at,
                PipelineProject.updated_at,
            )
            .where(
                PipelineProject.user_id == user_id,
                PipelineProject.deleted_at.is_(None),
            )
            .order_by(PipelineProject.updated_at.desc(), PipelineProject.created_at.desc())
        )
        items: List[Dict[str, Any]] = []
        for row in result.all():
            try:
                items.append(
                    {
                        "id": row.id,
                        "user_id": row.user_id,
                        "project_title": row.project_title or "未命名项目",
                        "current_step": int(row.current_step or 0),
                        "state": {},
                        "status": row.status or "draft",
                        "last_render_task_id": row.last_render_task_id or "",
                        "summary": row.summary or "",
                        "created_at": row.created_at.isoformat() if row.created_at else "",
                        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                    }
                )
            except Exception:
                logger.exception("Failed to serialize project list item: project_id=%s", getattr(row, "id", ""))
        return items

    async def get_project(self, db: AsyncSession, user_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineProject).where(
                PipelineProject.user_id == user_id,
                PipelineProject.id == project_id,
                PipelineProject.deleted_at.is_(None),
            )
        )
        project = result.scalar_one_or_none()
        return project.to_dict() if project else None

    async def get_current_project(self, db: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineProject)
            .where(
                PipelineProject.user_id == user_id,
                PipelineProject.deleted_at.is_(None),
            )
            .limit(1)
            .order_by(PipelineProject.updated_at.desc(), PipelineProject.created_at.desc())
        )
        project = result.scalars().first()
        return project.to_dict() if project else None

    async def create_project(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        project_title: str = "未命名项目",
        current_step: int = 0,
        state: Optional[Dict[str, Any]] = None,
        status: str = "draft",
        last_render_task_id: str = "",
        summary: str = "",
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        project = PipelineProject(
            id=uuid.uuid4().hex,
            user_id=user_id,
            project_title=project_title.strip() or "未命名项目",
            current_step=int(current_step or 0),
            state=state or {},
            status=status or "draft",
            last_render_task_id=last_render_task_id.strip() or None,
            summary=summary.strip() or None,
            created_at=now,
            updated_at=now,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project.to_dict()

    async def save_current_project(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[str] = None,
        user_id: str,
        project_title: str,
        current_step: int,
        state: Dict[str, Any],
        status: str = "draft",
        last_render_task_id: str = "",
        summary: str = "",
    ) -> Dict[str, Any]:
        project = None
        if project_id:
            result = await db.execute(
                select(PipelineProject).where(
                    PipelineProject.user_id == user_id,
                    PipelineProject.id == project_id,
                    PipelineProject.deleted_at.is_(None),
                )
            )
            project = result.scalar_one_or_none()
        if project is None:
            result = await db.execute(
                select(PipelineProject)
                .where(
                    PipelineProject.user_id == user_id,
                    PipelineProject.deleted_at.is_(None),
                )
                .limit(1)
                .order_by(PipelineProject.updated_at.desc(), PipelineProject.created_at.desc())
            )
            project = result.scalars().first()
        now = datetime.utcnow()

        if not project:
            project = PipelineProject(
                id=uuid.uuid4().hex,
                user_id=user_id,
                created_at=now,
            )
            db.add(project)

        project.project_title = project_title.strip() or "未命名项目"
        project.current_step = int(current_step or 0)
        project.state = state or {}
        project.status = status or "draft"
        project.last_render_task_id = last_render_task_id.strip() or None
        project.summary = summary.strip() or None
        project.updated_at = now

        await db.commit()
        await db.refresh(project)
        return project.to_dict()

    async def delete_project(self, db: AsyncSession, user_id: str, project_id: str) -> bool:
        result = await db.execute(
            select(PipelineProject).where(
                PipelineProject.user_id == user_id,
                PipelineProject.id == project_id,
                PipelineProject.deleted_at.is_(None),
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            return False

        project.deleted_at = datetime.utcnow()
        project.updated_at = project.deleted_at
        await db.commit()
        return True

    async def clear_current_project(self, db: AsyncSession, user_id: str) -> None:
        latest_project = await self.get_current_project(db, user_id)
        if latest_project:
            await self.delete_project(db, user_id, latest_project["id"])


pipeline_project_service = PipelineProjectService()
