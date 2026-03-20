"""
渲染任务的 Celery worker 入口。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from billiard.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_process_init, worker_process_shutdown

from app.celery_app import celery_app
from app.core.config import settings
from app.db.base import async_engine, sync_engine
from app.services.pipeline_workflow import pipeline_workflow_service

logger = logging.getLogger(__name__)
_worker_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run_async(awaitable):
    loop = _get_worker_loop()
    return loop.run_until_complete(awaitable)


async def _dispose_db_engines() -> None:
    try:
        await async_engine.dispose()
    except Exception as exc:
        logger.warning("Failed to dispose async engine cleanly: %s", exc)
    try:
        sync_engine.dispose()
    except Exception as exc:
        logger.warning("Failed to dispose sync engine cleanly: %s", exc)


@worker_process_init.connect
def _on_worker_process_init(**_: Any) -> None:
    loop = _get_worker_loop()
    try:
        loop.run_until_complete(_dispose_db_engines())
    except Exception as exc:
        logger.warning("Worker process init cleanup failed: %s", exc)


@worker_process_shutdown.connect
def _on_worker_process_shutdown(**_: Any) -> None:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        return
    try:
        _worker_loop.run_until_complete(_dispose_db_engines())
    except Exception as exc:
        logger.warning("Worker process shutdown cleanup failed: %s", exc)
    finally:
        _worker_loop.close()
        _worker_loop = None


def enqueue_render_task(task_id: str) -> None:
    run_render_task_job.apply_async(args=[task_id], task_id=task_id)


def revoke_render_task(task_id: str, *, terminate: bool = False) -> None:
    options = {"terminate": terminate}
    if terminate:
        options["signal"] = "SIGTERM"
    celery_app.control.revoke(task_id, **options)


@celery_app.task(
    name="pipeline.run_render_task",
    bind=True,
    soft_time_limit=settings.CELERY_RENDER_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.CELERY_RENDER_TASK_TIME_LIMIT,
)
def run_render_task_job(self, task_id: str) -> Dict[str, Any]:
    logger.info("Worker picked render task: %s", task_id)
    try:
        _run_async(pipeline_workflow_service.run_render_task(task_id))
    except SoftTimeLimitExceeded:
        logger.error("Render task soft time limit exceeded: %s", task_id, exc_info=True)
        _run_async(
            pipeline_workflow_service.mark_render_task_failed(
                task_id,
                error=(
                    "渲染任务执行超时，已被 worker 中断。"
                    f" 当前软超时为 {settings.CELERY_RENDER_TASK_SOFT_TIME_LIMIT} 秒，"
                    "请减少片段数量、缩短单次任务时长，或提高渲染任务超时配置后重试。"
                ),
                current_step="超时失败",
            )
        )
        raise
    state = pipeline_workflow_service.tasks.get(task_id)
    if state is None:
        state = _run_async(pipeline_workflow_service._load_render_task_state(task_id))
    if state and state.status == "failed":
        raise RuntimeError(state.error or f"Render task failed: {task_id}")
    return {
        "task_id": task_id,
        "status": state.status if state else "completed",
    }
