"""Hourly research runs off the Telegram event loop; no direct channel sends."""

import asyncio
import logging
from src.intelligence.hourly_research import run


async def hourly_research_job(context):
    try:
        await asyncio.to_thread(run)
    except Exception as exc:
        logging.getLogger(__name__).warning("Hourly research unavailable (%s)", type(exc).__name__)


def schedule_hourly_research(app):
    if not app.job_queue:
        logging.getLogger(__name__).warning("Hourly research not scheduled: JobQueue unavailable")
        return
    app.job_queue.run_repeating(hourly_research_job, interval=3600, first=90, name="hourly-research-desk",
        job_kwargs={"max_instances": 1, "coalesce": True, "misfire_grace_time": 120})
