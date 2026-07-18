# AccountsDashboard/celery.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "accounts.settings")

app = Celery("accounts")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ============================================================
# SCHEDULED TASKS (Celery Beat)
# ============================================================
app.conf.beat_schedule = {
    # Run daily reconciliation at 2 AM
    'run-daily-reconciliation': {
        'task': 'banklist.tasks.run_reconciliation_task',
        'schedule': crontab(hour=2, minute=0),
        'args': (1,),  # company_id - replace with dynamic if needed
    },
    # Process pending receipts at 3 AM
    'process-pending-receipts': {
        'task': 'banklist.tasks.process_all_receipts_task',
        'schedule': crontab(hour=3, minute=0),
        'args': (1,),  # company_id
    },
    # Clean up old audit logs at 4 AM (keep last 30 days)
    'cleanup-audit-logs': {
        'task': 'banklist.tasks.cleanup_audit_logs_task',
        'schedule': crontab(hour=4, minute=0),
        'args': (30,),  # keep last 30 days
    },
    # Check for failed tasks every hour
    'check-failed-tasks': {
        'task': 'banklist.tasks.check_failed_tasks_task',
        'schedule': crontab(minute=0),  # every hour
    },
}

# Optional: Configure task routing
app.conf.task_routes = {
    'banklist.tasks.parse_statement_task': {'queue': 'parsing'},
    'banklist.tasks.process_receipt_task': {'queue': 'parsing'},
    'banklist.tasks.run_reconciliation_task': {'queue': 'reconciliation'},
    'banklist.tasks.*': {'queue': 'default'},
}

# Optional: Task rate limits
app.conf.task_annotations = {
    'banklist.tasks.parse_statement_task': {'rate_limit': '10/m'},
    'banklist.tasks.process_receipt_task': {'rate_limit': '20/m'},
    'banklist.tasks.run_reconciliation_task': {'rate_limit': '2/m'},
}

# Optional: Task time limits (max runtime)
app.conf.task_time_limit = 3600  # 1 hour
app.conf.task_soft_time_limit = 3000  # 50 minutes