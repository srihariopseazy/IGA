from celery import shared_task


@shared_task(name="risk_tasks.run_risk_scoring")
def run_risk_scoring(*args, **kwargs):
    """Stub risk scoring task — delegates to tasks/risk_scoring.py."""
    pass
