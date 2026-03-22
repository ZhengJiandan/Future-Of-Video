import pytest

from app.core.config import settings
from app.services.pipeline_workflow import PipelineWorkflowService, RenderTaskState, RenderedClip


def _build_segment(segment_number: int) -> dict:
    return {
        "segment_number": segment_number,
        "title": f"片段 {segment_number}",
        "duration": 5.0,
        "description": f"片段 {segment_number} 描述",
        "video_prompt": f"片段 {segment_number} 提示词",
    }


def _build_state(*, task_id: str, auto_continue_segments: bool) -> RenderTaskState:
    segments = [_build_segment(1), _build_segment(2)]
    return RenderTaskState(
        task_id=task_id,
        user_id="user-1",
        project_id="project-1",
        project_title="测试项目",
        segments=segments,
        keyframes=[],
        character_profiles=[],
        scene_profiles=[],
        render_config={
            "provider": "local",
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "watermark": False,
            "provider_model": "",
            "camera_fixed": False,
            "generate_audio": False,
            "requested_generate_audio": False,
            "audio_strategy": "mute",
            "audio_plan": None,
            "return_last_frame": True,
            "auto_continue_segments": auto_continue_segments,
            "service_tier": "default",
            "seed": None,
        },
        clips=[
            RenderedClip(clip_number=1, title="片段 1", duration=5.0, description="片段 1 描述", video_prompt="prompt-1"),
            RenderedClip(clip_number=2, title="片段 2", duration=5.0, description="片段 2 描述", video_prompt="prompt-2"),
        ],
    )


@pytest.mark.asyncio
async def test_run_render_task_pauses_for_clip_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = PipelineWorkflowService()
    state = _build_state(task_id="task-confirmation", auto_continue_segments=False)
    service.tasks[state.task_id] = state

    async def fake_ensure_render_task_can_continue(task_id: str, state=None) -> None:
        return None

    async def fake_persist_render_task_state(*, state: RenderTaskState, user_id=None) -> None:
        return None

    async def fake_render_video_or_preview(**kwargs):
        segment = kwargs["segment"]
        return {
            "asset_url": f"/uploads/generated/pipeline/render/clip_{segment['segment_number']:02d}.mp4",
            "asset_type": "video/mp4",
            "asset_filename": f"clip_{segment['segment_number']:02d}.mp4",
            "provider": "local-preview",
        }

    monkeypatch.setattr(service, "_ensure_render_task_can_continue", fake_ensure_render_task_can_continue)
    monkeypatch.setattr(service, "_persist_render_task_state", fake_persist_render_task_state)
    monkeypatch.setattr(service, "_render_video_or_preview", fake_render_video_or_preview)

    await service.run_render_task(state.task_id)

    assert state.status == "paused"
    assert state.current_step == "等待确认继续生成片段 2/2"
    assert state.clips[0].status == "completed"
    assert state.clips[1].status == "queued"
    assert state.to_dict()["awaiting_confirmation"] is True
    assert state.to_dict()["next_clip_number"] == 2


@pytest.mark.asyncio
async def test_resume_render_task_updates_auto_continue_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PipelineWorkflowService()
    state = _build_state(task_id="task-resume", auto_continue_segments=False)
    state.status = "paused"
    state.current_step = "等待确认继续生成片段 2/2"
    service.tasks[state.task_id] = state

    async def fake_persist_render_task_state(*, state: RenderTaskState, user_id=None) -> None:
        return None

    async def fake_start_render_task(task_id: str, *, mark_failed_on_enqueue_error: bool = True) -> None:
        return None

    monkeypatch.setattr(service, "_persist_render_task_state", fake_persist_render_task_state)
    monkeypatch.setattr(service, "start_render_task", fake_start_render_task)

    resumed = await service.resume_render_task(
        state.task_id,
        user_id="user-1",
        auto_continue_segments=True,
    )

    assert resumed is state
    assert state.render_config["auto_continue_segments"] is True
    assert state.status == "queued"
    assert state.current_step == "等待重新投递"
