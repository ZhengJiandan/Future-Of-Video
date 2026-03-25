from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.pipeline_character_profile import PipelineCharacterProfile
from app.models.pipeline_project import PipelineProject
from app.models.pipeline_scene_profile import PipelineSceneProfile
from app.services.pipeline_character_library import PipelineCharacterLibraryService
from app.services.pipeline_project_service import PipelineProjectService
from app.services.pipeline_scene_library import PipelineSceneLibraryService


class _FakeScalarResult:
    def __init__(self, item):
        self._item = item

    def all(self):
        return list(self._item or [])

    def first(self):
        return self._item


class _FakeResult:
    def __init__(self, item):
        self._item = item

    def all(self):
        return list(self._item or [])

    def scalar_one_or_none(self):
        return self._item

    def scalar_one(self):
        return self._item

    def scalars(self):
        return _FakeScalarResult(self._item)


class _FakeAsyncSession:
    def __init__(self, *results) -> None:
        self._results = list(results)
        self.executed_statements = []
        self.commit_count = 0

    async def execute(self, statement):
        self.executed_statements.append(statement)
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commit_count += 1


def _build_project(project_id: str = "project-1") -> PipelineProject:
    now = datetime.utcnow()
    return PipelineProject(
        id=project_id,
        user_id="user-1",
        project_title="测试项目",
        current_step=1,
        state={"foo": "bar"},
        status="draft",
        created_at=now,
        updated_at=now,
    )


def _build_character(profile_id: str = "character-1") -> PipelineCharacterProfile:
    now = datetime.utcnow()
    return PipelineCharacterProfile(
        id=profile_id,
        name="测试角色",
        created_at=now,
        updated_at=now,
    )


def _build_scene(profile_id: str = "scene-1") -> PipelineSceneProfile:
    now = datetime.utcnow()
    return PipelineSceneProfile(
        id=profile_id,
        name="测试场景",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_project_soft_delete_keeps_record_but_hides_it_from_queries() -> None:
    service = PipelineProjectService()
    project = _build_project()

    delete_db = _FakeAsyncSession(_FakeResult(project))
    deleted = await service.delete_project(delete_db, "user-1", project.id)

    assert deleted is True
    assert project.deleted_at is not None
    assert delete_db.commit_count == 1

    get_db = _FakeAsyncSession(_FakeResult(project))
    await service.get_project(get_db, "user-1", project.id)
    assert "deleted_at IS NULL" in str(get_db.executed_statements[0])

    current_db = _FakeAsyncSession(_FakeResult(project))
    await service.get_current_project(current_db, "user-1")
    assert "deleted_at IS NULL" in str(current_db.executed_statements[0])

    list_row = SimpleNamespace(
        id=project.id,
        user_id=project.user_id,
        project_title=project.project_title,
        current_step=project.current_step,
        status=project.status,
        last_render_task_id=project.last_render_task_id,
        summary=project.summary,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
    list_db = _FakeAsyncSession(_FakeResult([list_row]))
    items = await service.list_projects(list_db, "user-1")
    assert "deleted_at IS NULL" in str(list_db.executed_statements[0])
    assert [item["id"] for item in items] == [project.id]


@pytest.mark.asyncio
async def test_character_soft_delete_keeps_record_and_filters_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineCharacterLibraryService()
    profile = _build_character()

    def fail_delete_local_asset(_path: str | None) -> None:
        raise AssertionError("soft delete should not remove local assets")

    async def noop_backfill(_db, _profiles) -> None:
        return None

    monkeypatch.setattr(service, "_delete_local_asset", fail_delete_local_asset)
    monkeypatch.setattr(service, "_backfill_missing_face_closeups", noop_backfill)

    delete_db = _FakeAsyncSession(_FakeResult(profile))
    deleted = await service.delete_profile(delete_db, profile.id)

    assert deleted is True
    assert profile.deleted_at is not None
    assert delete_db.commit_count == 1

    get_db = _FakeAsyncSession(_FakeResult(profile))
    await service.get_profile_by_id(get_db, profile.id)
    assert "deleted_at IS NULL" in str(get_db.executed_statements[0])

    list_db = _FakeAsyncSession(_FakeResult([profile]))
    items = await service.list_profiles(list_db)
    assert "deleted_at IS NULL" in str(list_db.executed_statements[0])
    assert [item["id"] for item in items] == [profile.id]


@pytest.mark.asyncio
async def test_scene_soft_delete_keeps_record_and_filters_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineSceneLibraryService()
    profile = _build_scene()

    def fail_delete_local_asset(_path: str | None) -> None:
        raise AssertionError("soft delete should not remove local assets")

    monkeypatch.setattr(service, "_delete_local_asset", fail_delete_local_asset)

    delete_db = _FakeAsyncSession(_FakeResult(profile))
    deleted = await service.delete_profile(delete_db, profile.id)

    assert deleted is True
    assert profile.deleted_at is not None
    assert delete_db.commit_count == 1

    get_db = _FakeAsyncSession(_FakeResult(profile))
    await service.get_profile_by_id(get_db, profile.id)
    assert "deleted_at IS NULL" in str(get_db.executed_statements[0])

    list_db = _FakeAsyncSession(_FakeResult([profile]))
    items = await service.list_profiles(list_db)
    assert "deleted_at IS NULL" in str(list_db.executed_statements[0])
    assert [item["id"] for item in items] == [profile.id]
