from celery import shared_task


@shared_task(name="provisioning_tasks.run_provisioning")
def run_provisioning(*args, **kwargs):
    """Stub provisioning task — delegates to tasks/provisioning.py."""
    pass
