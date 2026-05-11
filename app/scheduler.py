import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .blacklist_job import run_all_blacklist_checks
from .config import get_settings
from .imap_poller import poll_all_enabled
from .mt_worker import poll_mailtest_inbox
from .notifications import send_weekly_digest

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        poll_all_enabled, "interval",
        minutes=max(1, settings.imap_poll_interval_minutes),
        id="imap_poll", max_instances=1, coalesce=True, replace_existing=True,
    )
    # Weekly digest: Mondays 07:00 UTC
    sched.add_job(
        send_weekly_digest, CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="weekly_digest", max_instances=1, coalesce=True, replace_existing=True,
    )
    # DNSBL / Blacklist scan: daily 06:00 UTC
    sched.add_job(
        run_all_blacklist_checks, CronTrigger(hour=6, minute=0),
        id="blacklist_scan", max_instances=1, coalesce=True, replace_existing=True,
    )
    # Mail-Tester: pollt die Catch-All-Inbox sobald MAILTEST_* configured ist
    sched.add_job(
        poll_mailtest_inbox, "interval",
        seconds=max(10, settings.mailtest_poll_seconds),
        id="mailtest_poll", max_instances=1, coalesce=True, replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler started (poll=%s min, weekly digest mon 07:00 UTC, blacklist daily 06:00 UTC)",
             settings.imap_poll_interval_minutes)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
