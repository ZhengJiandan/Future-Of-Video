from __future__ import annotations

from datetime import datetime

import pytest

from app.models.pipeline_project import PipelineProject
from app.services.pipeline_project_service import PipelineProjectService


class _FakeScalarResult:
    def __init__(self, item):
        self._item = item

    def first(self):
        return self._item


class _FakeResult:
    def __init__(self, item):
        self._item = item

    def scalars(self):
        return _FakeScalarResult(self._item)


class _FakeSession:
    def __init__(self, *results):
        self._results = list(results)
        self.added = []

    async def execute(self, _statement):
        return self._results.pop(0)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        return None

    async def refresh(self, _item):
        return None


def _build_project(project_id: str, title: str) -> PipelineProject:
    now = datetime.utcnow()
    project = PipelineProject(
        id=project_id,
        user_id="user-1",
        project_title=title,
        current_step=1,
        state={"foo": "bar"},
        status="draft",
        created_at=now,
        updated_at=now,
    )
    return project


@pytest.mark.asyncio
async def test_get_current_project_returns_first_item_without_multiple_results_error() -> None:
    service = PipelineProjectService()
    latest = _build_project("p-latest", "最新项目")
    db = _FakeSession(_FakeResult(latest))

    result = await service.get_current_project(db, "user-1")

    assert result is not None
    assert result["id"] == "p-latest"
    assert result["project_title"] == "最新项目"


@pytest.mark.asyncio
async def test_save_current_project_reuses_first_existing_project_when_no_project_id() -> None:
    service = PipelineProjectService()
    existing = _build_project("p-existing", "旧标题")
    db = _FakeSession(_FakeResult(existing))

    result = await service.save_current_project(
        db,
        user_id="user-1",
        project_title="新标题",
        current_step=3,
        state={"currentStep": 3},
        status="in_progress",
        last_render_task_id="task-1",
        summary="摘要",
    )

    assert result["id"] == "p-existing"
    assert result["project_title"] == "新标题"
    assert result["current_step"] == 3
    assert result["status"] == "in_progress"
    assert result["last_render_task_id"] == "task-1"
