from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_project import PipelineProject


class PipelineProjectService:
    async def list_projects(self, db: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineProject)
            .where(PipelineProject.user_id == user_id)
            .order_by(PipelineProject.updated_at.desc(), PipelineProject.created_at.desc())
        )
        return [project.to_dict() for project in result.scalars().all()]

    async def get_project(self, db: AsyncSession, user_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineProject).where(
                PipelineProject.user_id == user_id,
                PipelineProject.id == project_id,
            )
        )
        project = result.scalar_one_or_none()
        return project.to_dict() if project else None

    async def get_current_project(self, db: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(PipelineProject)
            .where(PipelineProject.user_id == user_id)
            .order_by(PipelineProject.updated_at.desc(), PipelineProject.created_at.desc())
        )
        project = result.scalar_one_or_none()
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
                )
            )
            project = result.scalar_one_or_none()
        if project is None:
            result = await db.execute(
                select(PipelineProject)
                .where(PipelineProject.user_id == user_id)
                .order_by(PipelineProject.updated_at.desc(), PipelineProject.created_at.desc())
            )
            project = result.scalar_one_or_none()
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
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            return False

        await db.execute(
            delete(PipelineProject).where(
                PipelineProject.user_id == user_id,
                PipelineProject.id == project_id,
            )
        )
        await db.commit()
        return True

    async def clear_current_project(self, db: AsyncSession, user_id: str) -> None:
        latest_project = await self.get_current_project(db, user_id)
        if latest_project:
            await self.delete_project(db, user_id, latest_project["id"])


pipeline_project_service = PipelineProjectService()
