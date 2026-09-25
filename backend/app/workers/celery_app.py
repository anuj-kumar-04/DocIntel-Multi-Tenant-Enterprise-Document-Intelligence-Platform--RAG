from celery import Celery
from app.config import settings

celery_app = Celery(
    "docintel",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        "app.workers.tasks.ingest_document": {"queue": "document_ingestion"},
    },
)
