"""Two pre-open snapshots and one after-close outcome check in New York time."""

import asyncio
from datetime import datetime,time,timezone
import logging

from src.config.premarket import settings
from src.config.special_alerts import settings as special_settings
from src.intelligence import premarket_sources as sources,premarket_disclosures as disclosures,premarket_risk as risk,premarket_store as store
from src.intelligence import special_alert_store as special_store
from src.jobs.special_alert_scheduler import destinations

LOG=logging.getLogger(__name__)


def utc_now():return datetime.now(timezone.utc)


def active():
    return settings()["enabled"] and store.enabled() and special_settings()["enabled"] and special_store.get_settings().get("enabled",True)


def collect_snapshot(slot="preview",now=None):
    fixed=now is not None
    now=now or utc_now();config=settings()
    quotes,issues=sources.collect(now,config);documents=[]
    if quotes:
        documents,limited=disclosures.collect(now,datetime.fromisoformat(quotes["SPY"]["session"]["previous_close"]))
        issues+=limited
    cutoff=now if fixed else utc_now()
    if not sources.window(cutoff):quotes,documents={},[]
    return risk.snapshot(quotes,documents,issues,cutoff,config,slot)


async def premarket_job(context):
    slot=context.job.data
    try:
        now=utc_now()
        if not active() or not sources.window(now):return
        due=now.astimezone(sources.NY).replace(hour=int(slot[:2]),minute=int(slot[3:]),second=0,microsecond=0)
        if not 0<=(now-due).total_seconds()<600:return
        day=now.astimezone(sources.NY).date().isoformat()
        if any(row["slot"]==slot for row in store.history(2,day)):return
        value=await asyncio.to_thread(collect_snapshot,slot)
        value=store.save(value)
        text=risk.render(value)
        if len(text)>3900:raise ValueError("Premarket warning exceeds its message budget")
        for chat in destinations():
            at=utc_now()
            if not active() or not sources.window(at):return
            if not store.claim(value,chat,at):continue
            try:
                await context.bot.send_message(chat_id=chat,text=text,parse_mode=None,disable_web_page_preview=True)
            except Exception as error:
                store.finish(value,chat,utc_now(),False)
                LOG.warning("Premarket delivery failed (%s)",type(error).__name__)
            else:store.finish(value,chat,utc_now(),True)
    except Exception as error:LOG.exception("Premarket check unavailable (%s)",type(error).__name__)


async def outcome_job(context):
    from src.intelligence.premarket_review import observe
    try:
        now=utc_now();day=now.astimezone(sources.NY).date().isoformat()
        if not active() or day in store.outcomes():return
        value=await asyncio.to_thread(observe,now)
        store.save_outcome(day,value)
    except Exception as error:LOG.warning("Premarket outcome review unavailable (%s)",type(error).__name__)


def schedule_premarket(app):
    if not app.job_queue:
        LOG.warning("Premarket checks not scheduled: JobQueue unavailable");return
    for hour,minute in ((8,45),(9,15)):
        slot=f"{hour:02d}:{minute:02d}"
        app.job_queue.run_daily(premarket_job,time=time(hour,minute,tzinfo=sources.NY),days=(1,2,3,4,5),data=slot,
            name="premarket-"+slot,job_kwargs={"max_instances":1,"coalesce":True,"misfire_grace_time":120})
    app.job_queue.run_daily(outcome_job,time=time(16,20,tzinfo=sources.NY),days=(1,2,3,4,5),name="premarket-outcome",
        job_kwargs={"max_instances":1,"coalesce":True,"misfire_grace_time":300})
