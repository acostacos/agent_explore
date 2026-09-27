"""Weekly APScheduler job for the Strands research agent."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.agent import ResearchAgent
from app.config import get_settings

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_started = False


def _run_agent_job() -> None:
    logger.info("Starting scheduled weekly Strands research run")
    agent = ResearchAgent()
    try:
        asyncio.run(agent.run(trigger="scheduled"))
    except Exception:
        logger.exception("Scheduled research run failed")


def start_scheduler() -> BackgroundScheduler:
    global _started
    if _started:
        return scheduler

    settings = get_settings()
    trigger = CronTrigger(
        day_of_week=settings.schedule_day_of_week,
        hour=settings.schedule_hour,
        minute=settings.schedule_minute,
    )
    scheduler.add_job(
        _run_agent_job,
        trigger=trigger,
        id="weekly_paper_research",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _started = True
    logger.info(
        "Scheduler started — weekly Strands run on %s at %02d:%02d",
        settings.schedule_day_of_week,
        settings.schedule_hour,
        settings.schedule_minute,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _started
    if scheduler.running:
        scheduler.shutdown(wait=False)
    _started = False


def next_run_time() -> str | None:
    job = scheduler.get_job("weekly_paper_research")
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()
