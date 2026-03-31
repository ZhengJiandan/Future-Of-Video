import asyncio

import pytest

from app.core.config import Settings, settings
from app.services.pipeline_workflow import (
    PipelineWorkflowService,
    RenderTaskState,
    SUBMITTED_TO_LOCAL_STEP,
)


def _build_render_state(task_id: str = "task-local-1") -> RenderTaskState:
    return RenderTaskState(
        task_id=task_id,
        user_id="user-1",
        project_id="project-1",
        project_title="测试项目",
        segments=[],
        keyframes=[],
        character_profiles=[],
        scene_profiles=[],
        render_config={},
    )


def test_settings_accept_local_runtime_alias() -> None:
    configured = Settings(PIPELINE_RUNTIME_MODE="local")

    assert configured.PIPELINE_RUNTIME_MODE == "minimal"
    assert configured.pipeline_uses_local_render_dispatch is True
    assert configured.pipeline_render_dispatch_mode == "local"


def test_auto_render_provider_prefers_kling_over_doubao(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PipelineWorkflowService()
    monkeypatch.setattr(service, "_kling_enabled", lambda: True)
    monkeypatch.setattr(service, "_doubao_enabled", lambda: True)

    assert service._choose_render_provider({"provider": "auto"}) == "kling-official"


def test_auto_render_provider_falls_back_to_doubao_when_kling_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PipelineWorkflowService()
    monkeypatch.setattr(service, "_kling_enabled", lambda: False)
    monkeypatch.setattr(service, "_doubao_enabled", lambda: True)

    assert service._choose_render_provider({"provider": "auto"}) == "doubao-official"


def test_select_character_profiles_for_segment_uses_segment_character_ids() -> None:
    service = PipelineWorkflowService()
    character_profiles = [
        {"id": "char-a", "name": "角色A"},
        {"id": "char-b", "name": "角色B"},
        {"id": "char-c", "name": "角色C"},
    ]
    segment = {
        "character_profile_ids": ["char-a"],
        "late_entry_character_profile_ids": ["char-b"],
        "key_dialogues": [{"text": "台词", "speaker_character_id": "char-c"}],
    }

    result = service._select_character_profiles_for_segment(
        segment=segment,
        character_profiles=character_profiles,
    )

    assert [item["id"] for item in result] == ["char-a", "char-b", "char-c"]


@pytest.mark.asyncio
async def test_generate_keyframes_passes_only_segment_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PipelineWorkflowService()
    captured: list[list[str]] = []

    async def fake_generate_keyframe_asset(**kwargs):
        captured.append([str(item.get("id") or "") for item in kwargs["character_profiles"]])
        from app.services.pipeline_workflow import KeyframeAsset

        return KeyframeAsset(
            asset_url="/uploads/generated/pipeline/keyframes/segment_01_start.png",
            asset_type="image/png",
            asset_filename="segment_01_start.png",
            prompt="prompt",
            source="test",
        )

    monkeypatch.setattr(service, "_generate_keyframe_asset", fake_generate_keyframe_asset)

    result = await service.generate_keyframes(
        project_title="测试项目",
        segments=[
            {
                "segment_number": 1,
                "title": "片段 1",
                "duration": 5.0,
                "character_profile_ids": ["char-b"],
                "pre_generate_start_frame": True,
            }
        ],
        style="写实",
        character_profiles=[
            {"id": "char-a", "name": "角色A"},
            {"id": "char-b", "name": "角色B"},
            {"id": "char-c", "name": "角色C"},
        ],
        scene_profiles=[],
        reference_images=[],
    )

    assert captured == [["char-b"]]
    assert result["keyframes"][0]["segment_number"] == 1


@pytest.mark.asyncio
async def test_start_render_task_runs_in_local_process_when_minimal_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineWorkflowService()
    state = _build_render_state()
    service.tasks[state.task_id] = state

    started = asyncio.Event()
    persisted_steps: list[tuple[str, str]] = []

    async def fake_claim_render_task_for_dispatch(task_id: str):
        assert task_id == state.task_id
        return state

    async def fake_persist_render_task_state(*, state: RenderTaskState, user_id=None):
        persisted_steps.append((state.status, state.current_step))

    async def fake_run_render_task(task_id: str) -> None:
        assert task_id == state.task_id
        started.set()

    async def fake_ensure_render_task_can_continue(task_id: str, state=None) -> None:
        return None

    monkeypatch.setattr(settings, "PIPELINE_RUNTIME_MODE", "minimal")
    monkeypatch.setattr(service, "_claim_render_task_for_dispatch", fake_claim_render_task_for_dispatch)
    monkeypatch.setattr(service, "_persist_render_task_state", fake_persist_render_task_state)
    monkeypatch.setattr(service, "_ensure_render_task_can_continue", fake_ensure_render_task_can_continue)
    monkeypatch.setattr(service, "run_render_task", fake_run_render_task)

    await service.start_render_task(state.task_id)
    await asyncio.wait_for(started.wait(), timeout=1.0)

    assert persisted_steps[-1] == ("queued", SUBMITTED_TO_LOCAL_STEP)
    assert state.current_step == SUBMITTED_TO_LOCAL_STEP
    assert state.error == ""
