from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.pipeline_character_library import PipelineCharacterLibraryService


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.added = None

    def add(self, instance) -> None:
        self.added = instance

    async def commit(self) -> None:
        return None

    async def refresh(self, instance) -> None:
        return None


@pytest.mark.asyncio
async def test_create_profile_skips_identity_asset_generation_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = PipelineCharacterLibraryService()
    db = _FakeAsyncSession()

    async def fail_generate_three_view_asset(**kwargs):
        raise AssertionError("three-view generation should be skipped")

    def fail_generate_face_closeup_asset(reference_image_url: str) -> str:
        raise AssertionError("face closeup generation should be skipped")

    monkeypatch.setattr(service, "generate_three_view_asset", fail_generate_three_view_asset)
    monkeypatch.setattr(service, "_generate_face_closeup_asset", fail_generate_face_closeup_asset)

    result = await service.create_profile(
        db,
        {
            "name": "测试角色",
            "role": "主角",
            "reference_image_url": "/uploads/generated/pipeline/keyframes/segment_01_start.png",
            "reference_image_original_name": "segment_01_start.png",
            "auto_generate_identity_assets": False,
        },
    )

    assert result["reference_image_url"] == "/uploads/generated/pipeline/keyframes/segment_01_start.png"
    assert result["three_view_image_url"] == ""
    assert result["face_closeup_image_url"] == ""
    assert result["reference_image_original_name"] == "segment_01_start.png"
    assert result["source"] == "library"


@pytest.mark.asyncio
async def test_create_profile_enqueues_three_view_generation_in_background(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = PipelineCharacterLibraryService()
    db = _FakeAsyncSession()
    queued: dict[str, str] = {}

    async def fail_generate_three_view_asset(**kwargs):
        raise AssertionError("three-view generation should run in background")

    def fake_generate_face_closeup_asset(reference_image_url: str) -> str:
        return ""

    def fake_enqueue_three_view_generation(**kwargs) -> None:
        queued.update({key: str(value) for key, value in kwargs.items()})

    monkeypatch.setattr(service, "generate_three_view_asset", fail_generate_three_view_asset)
    monkeypatch.setattr(service, "_generate_face_closeup_asset", fake_generate_face_closeup_asset)
    monkeypatch.setattr(service, "_enqueue_three_view_generation", fake_enqueue_three_view_generation)

    result = await service.create_profile(
        db,
        {
            "name": "测试角色",
            "role": "主角",
            "reference_image_url": "/uploads/generated/pipeline/keyframes/segment_01_start.png",
            "reference_image_original_name": "segment_01_start.png",
        },
    )

    assert result["three_view_image_url"] == ""
    assert queued["profile_id"] == result["id"]
    assert queued["expected_reference_image_url"] == "/uploads/generated/pipeline/keyframes/segment_01_start.png"
    assert queued["expected_current_three_view_url"] == ""
