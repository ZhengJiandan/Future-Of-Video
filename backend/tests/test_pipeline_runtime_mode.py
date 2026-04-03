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


def test_standard_render_config_defaults_to_kling_omni() -> None:
    service = PipelineWorkflowService()

    config = service._normalize_render_config({"workflow_mode": "standard"})

    assert config["provider"] == "kling"
    assert config["provider_model"] == "kling-v3-omni"


def test_standard_segment_defaults_to_single_shot_without_explicit_llm_config() -> None:
    service = PipelineWorkflowService()
    segment = {
        "segment_number": 1,
        "title": "片段 1",
        "duration": 8.0,
        "shots_summary": "开场推进角色进入厂房；随后切到近景确认目标；最后转到撤离时的追逐状态",
        "key_actions": ["进入厂房", "确认目标", "转身撤离"],
        "key_dialogues": [{"text": "找到目标了"}, {"text": "立刻撤离"}],
        "generation_config": {},
    }

    enriched = service._apply_segment_render_generation_config(
        segment=segment,
        character_profiles=[
            {"id": "char-a", "name": "角色A", "video_prompt_base": "冷静特工，黑色战术服"},
            {"id": "char-b", "name": "角色B", "video_prompt_base": "搭档，灰色风衣"},
        ],
        scene_profiles=[],
        render_config={"workflow_mode": "standard", "provider_model": "kling-v3-omni"},
    )

    generation_config = enriched["generation_config"]
    assert generation_config["kling_multi_shot_enabled"] is False
    assert generation_config["kling_multi_shot_source"] == "default_single_shot"
    assert "kling_shot_type" not in generation_config
    assert "kling_multi_prompt" not in generation_config


def test_standard_segment_preserves_explicit_llm_multi_shot_config() -> None:
    service = PipelineWorkflowService()
    segment = {
        "segment_number": 1,
        "title": "片段 1",
        "duration": 8.0,
        "generation_config": {
            "kling_multi_shot_enabled": True,
            "kling_shot_type": "customize",
            "kling_multi_prompt": ["分镜一 prompt", "分镜二 prompt"],
            "kling_multi_shot_reason": "大模型判断该片段更适合多镜头推进",
            "kling_multi_shot_source": "llm-script-splitter",
        },
    }

    enriched = service._apply_segment_render_generation_config(
        segment=segment,
        character_profiles=[],
        scene_profiles=[],
        render_config={"workflow_mode": "standard", "provider_model": "kling-v3-omni"},
    )

    generation_config = enriched["generation_config"]
    assert generation_config["kling_multi_shot_enabled"] is True
    assert generation_config["kling_shot_type"] == "customize"
    assert generation_config["kling_multi_prompt"] == ["分镜一 prompt", "分镜二 prompt"]
    assert generation_config["kling_multi_shot_reason"] == "大模型判断该片段更适合多镜头推进；片段已提供显式 multi_prompt，可直接启用多镜头模式"
    assert generation_config["kling_multi_shot_source"] == "llm-script-splitter"


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
async def test_generate_keyframes_regenerates_only_target_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PipelineWorkflowService()
    captured_segments: list[int] = []

    async def fake_generate_keyframe_asset(**kwargs):
        captured_segments.append(int(kwargs["segment"]["segment_number"]))
        from app.services.pipeline_workflow import KeyframeAsset

        segment_number = int(kwargs["segment"]["segment_number"])
        return KeyframeAsset(
            asset_url=f"/uploads/generated/pipeline/keyframes/segment_{segment_number:02d}_start_new.png",
            asset_type="image/png",
            asset_filename=f"segment_{segment_number:02d}_start_new.png",
            prompt=f"prompt-{segment_number}",
            source="test",
        )

    monkeypatch.setattr(service, "_generate_keyframe_asset", fake_generate_keyframe_asset)

    result = await service.generate_keyframes(
        project_title="测试项目",
        segments=[
            {"segment_number": 1, "title": "片段 1", "duration": 5.0},
            {"segment_number": 2, "title": "片段 2", "duration": 5.0},
        ],
        style="写实",
        character_profiles=[],
        scene_profiles=[],
        reference_images=[],
        existing_keyframes=[
            {
                "segment_number": 1,
                "title": "片段 1",
                "start_frame": {
                    "asset_url": "/uploads/generated/pipeline/keyframes/segment_01_start_existing.png",
                    "asset_type": "image/png",
                    "asset_filename": "segment_01_start_existing.png",
                    "prompt": "existing",
                    "source": "existing",
                    "status": "completed",
                    "notes": "",
                    "thumbnail_url": "",
                },
                "end_frame": {
                    "asset_url": "",
                    "asset_type": "image/png",
                    "asset_filename": "",
                    "prompt": "",
                    "source": "not-used-in-standard-workflow",
                    "status": "skipped",
                    "notes": "",
                    "thumbnail_url": "",
                },
                "continuity_notes": "existing-notes",
                "status": "ready",
            }
        ],
        target_segment_number=2,
    )

    assert captured_segments == [2]
    assert result["keyframes"][0]["start_frame"]["asset_url"] == "/uploads/generated/pipeline/keyframes/segment_01_start_existing.png"
    assert result["keyframes"][1]["start_frame"]["asset_url"] == "/uploads/generated/pipeline/keyframes/segment_02_start_new.png"


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
