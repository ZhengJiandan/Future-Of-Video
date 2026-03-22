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
