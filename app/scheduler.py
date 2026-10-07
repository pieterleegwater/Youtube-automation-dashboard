from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import pipeline
from .config import settings

JOB_NAMES = {
    "generate": "Video genereren",
    "upload": "Uploaden naar YouTube",
    "stats": "Statistieken ophalen",
    "evolve": "Strategieën bijsturen",
}


def create_scheduler() -> BackgroundScheduler:
    tz = settings.timezone
    scheduler = BackgroundScheduler(timezone=tz, job_defaults={"coalesce": True, "misfire_grace_time": 3600})
    gh, gm = settings.generate_time
    uh, um = settings.upload_time
    eh, em = settings.evolve_time
    scheduler.add_job(pipeline.generate_today, CronTrigger(hour=gh, minute=gm, timezone=tz), id="generate")
    scheduler.add_job(pipeline.upload_today, CronTrigger(hour=uh, minute=um, timezone=tz), id="upload")
    scheduler.add_job(pipeline.sync_stats, IntervalTrigger(hours=settings.stats_interval_hours), id="stats")
    scheduler.add_job(
        pipeline.evolve_strategies,
        CronTrigger(day_of_week=settings.evolve_day, hour=eh, minute=em, timezone=tz),
        id="evolve",
    )
    return scheduler
