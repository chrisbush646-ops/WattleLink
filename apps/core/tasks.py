import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def smoke_test():
    logger.info("Celery is working")
    return "Celery is working"
