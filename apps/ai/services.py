"""Shared AI helpers: task progress tracking via Django cache."""
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

_PROGRESS_TIMEOUT = 3600  # 1 hour


def set_task_progress(task_id: str, status: str, message: str) -> None:
    """Store progress state for a Celery task so status endpoints can surface it."""
    cache.set(
        f"task_progress:{task_id}",
        {"status": status, "message": message},
        timeout=_PROGRESS_TIMEOUT,
    )


def get_task_progress(task_id: str) -> dict:
    """Return the latest progress dict for a task, or a default if not set."""
    return cache.get(f"task_progress:{task_id}") or {"status": "pending", "message": "Queued…"}
