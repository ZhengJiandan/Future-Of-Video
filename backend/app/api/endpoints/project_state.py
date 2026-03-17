from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.auth_service import get_current_user
from app.services.pipeline_project_service import pipeline_project_service


router = APIRouter()


class SaveCurrentProjectRequest(BaseModel):
    project_title: str = Field(default="未命名项目")
    current_step: int = Field(default=0, ge=0, le=10)
    state: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="draft")
    last_render_task_id: str = Field(default="")
    summary: str = Field(default="")
    project_id: Optional[str] = Field(default=None)


class CreateProjectRequest(BaseModel):
    project_title: str = Field(default="未命名项目")
    current_step: int = Field(default=0, ge=0, le=10)
    state: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="draft")
    last_render_task_id: str = Field(default="")
    summary: str = Field(default="")


@router.get("")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items = await pipeline_project_service.list_projects(db, current_user.id)
    return {
        "success": True,
        "items": items,
    }


@router.post("")
async def create_project(
    request: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = await pipeline_project_service.create_project(
        db,
        user_id=current_user.id,
        project_title=request.project_title,
        current_step=request.current_step,
        state=request.state,
        status=request.status,
        last_render_task_id=request.last_render_task_id,
        summary=request.summary,
    )
    return {
        "success": True,
        "message": "项目已创建",
        "item": item,
    }


@router.get("/current")
async def get_current_project(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = await pipeline_project_service.get_current_project(db, current_user.id)
    return {
        "success": True,
        "item": item,
    }


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = await pipeline_project_service.get_project(db, current_user.id, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "success": True,
        "item": item,
    }


@router.put("/current")
async def save_current_project(
    request: SaveCurrentProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = await pipeline_project_service.save_current_project(
        db,
        project_id=request.project_id,
        user_id=current_user.id,
        project_title=request.project_title,
        current_step=request.current_step,
        state=request.state,
        status=request.status,
        last_render_task_id=request.last_render_task_id,
        summary=request.summary,
    )
    return {
        "success": True,
        "message": "项目进度已保存",
        "item": item,
    }


@router.put("/{project_id}")
async def save_project(
    project_id: str,
    request: SaveCurrentProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = await pipeline_project_service.save_current_project(
        db,
        project_id=project_id,
        user_id=current_user.id,
        project_title=request.project_title,
        current_step=request.current_step,
        state=request.state,
        status=request.status,
        last_render_task_id=request.last_render_task_id,
        summary=request.summary,
    )
    return {
        "success": True,
        "message": "项目已保存",
        "item": item,
    }


@router.delete("/current")
async def clear_current_project(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await pipeline_project_service.clear_current_project(db, current_user.id)
    return {
        "success": True,
        "message": "当前项目草稿已清除",
    }


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    deleted = await pipeline_project_service.delete_project(db, current_user.id, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "success": True,
        "message": "项目已删除",
    }
