from celery import shared_task


@shared_task(name="compliance_tasks.run_compliance_check")
def run_compliance_check(*args, **kwargs):
    """Stub compliance check task."""
    pass
