"""
Celery 应用入口。
"""
from celery import Celery

from app.core.config import settings


celery_app = Celery("future_of_video")
celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=settings.CELERY_ENABLE_UTC,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    broker_transport_options={
        "visibility_timeout": max(
            settings.CELERY_TASK_TIME_LIMIT,
            settings.CELERY_RENDER_TASK_TIME_LIMIT,
        )
        * 2,
    },
)
celery_app.conf.imports = ("app.workers.render_tasks",)
celery_app.autodiscover_tasks(["app"])
