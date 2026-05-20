from celery import Celery
from celery.schedules import crontab
from backend.config import settings

celery_app = Celery(
    "iga",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "backend.tasks.provisioning",
        "backend.tasks.certification",
        "backend.tasks.risk_scoring",
        "backend.tasks.sod_scan",
        "backend.tasks.notification",
        "backend.tasks.sync",
        "backend.tasks.cleanup",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=300,   # 5 minutes soft limit
    task_time_limit=600,        # 10 minutes hard limit
    result_expires=86400,       # results kept for 24 hours
    worker_max_tasks_per_child=1000,
    beat_schedule={
        "sod-scan-daily": {
            "task": "backend.tasks.sod_scan.scan_all_tenants",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "sod"},
        },
        "risk-score-update": {
            "task": "backend.tasks.risk_scoring.update_all_risk_scores",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "risk"},
        },
        "certification-deadline-check": {
            "task": "backend.tasks.certification.check_deadlines",
            "schedule": crontab(hour="*/4", minute=0),
            "options": {"queue": "certification"},
        },
        "session-cleanup": {
            "task": "backend.tasks.cleanup.cleanup_expired_sessions",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "cleanup"},
        },
        "provisioning-retry": {
            "task": "backend.tasks.provisioning.retry_failed_tasks",
            "schedule": crontab(minute="*/5"),
            "options": {"queue": "provisioning"},
        },
        "expired-token-cleanup": {
            "task": "backend.tasks.cleanup.cleanup_expired_tokens",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "cleanup"},
        },
        "deactivate-expired-access": {
            "task": "backend.tasks.cleanup.deactivate_expired_access",
            "schedule": crontab(minute="*/10"),
            "options": {"queue": "provisioning"},
        },
        "audit-log-archive": {
            "task": "backend.tasks.cleanup.archive_old_audit_logs",
            "schedule": crontab(hour=1, minute=0, day_of_week=0),  # weekly Sunday 1am
            "options": {"queue": "cleanup"},
        },
    },
)

celery_app.conf.task_routes = {
    "backend.tasks.provisioning.*": {"queue": "provisioning"},
    "backend.tasks.certification.*": {"queue": "certification"},
    "backend.tasks.risk_scoring.*": {"queue": "risk"},
    "backend.tasks.sod_scan.*": {"queue": "sod"},
    "backend.tasks.notification.*": {"queue": "notification"},
    "backend.tasks.sync.*": {"queue": "sync"},
    "backend.tasks.cleanup.*": {"queue": "cleanup"},
}
