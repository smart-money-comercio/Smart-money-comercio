"""Separate weekly evidence admission; daily news freshness rules are unchanged."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import sqlite3
from urllib.parse import quote
from zoneinfo import ZoneInfo

from src.intelligence import news_live_sources as feeds, news_editor as editor, news_original_sources as originals
from src.intelligence import story_analysis as analysis, company_schedule, calendar_context, calendar_sources
from src.utils.yahoo_quote import parse_regular_quote, finite_number, source_time
from src.utils.market_quote_source import source_evidence, BENCHMARKS

NY = ZoneInfo("America/New_York")
MAX_BODY_READS = 6


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def clock(value):
    if not isinstance(value, str):
        raise ValueError("A source clock is missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = parsedate_to_datetime(value)
    if result.tzinfo is None:
        raise ValueError("A source clock has no timezone")
    return result.astimezone(timezone.utc)


def window(now):
    if now.tzinfo is None or now.astimezone(NY).weekday() not in {5, 6}:
        raise ValueError("Build the Weekend Outlook on Saturday or Sunday, New York time")
    local = now.astimezone(NY)
    monday = local.date()-timedelta(days=local.weekday())
    friday = monday+timedelta(days=4)
    return {"week_start":monday.isoformat(), "week_end":friday.isoformat(),
            "baseline_date":(monday-timedelta(days=3)).isoformat(),
            "evidence_start":datetime.combine(monday,datetime.min.time(),NY).isoformat(),
            "evidence_end":now.astimezone(timezone.utc).isoformat(),
            "next_start":(monday+timedelta(days=7)).isoformat(), "next_end":(monday+timedelta(days=11)).isoformat()}


def fresh(value, now):
    stamp = clock(value) if isinstance(value, str) else source_time(value)
    if stamp is None or not -60 <= (now-stamp).total_seconds() <= 21600:
        raise ValueError("Source observation is stale or future-dated")
    return stamp


def market_url(symbol):
    if symbol not in BENCHMARKS:
        raise ValueError("Weekly price instrument is not configured")
    return "https://query1.finance.yahoo.com/v8/finance/chart/"+quote(symbol,safe="")+"?range=1mo&interval=1d&events=splits"


def price_packet(symbol, result, observed, periods, now):
    observed = fresh(observed,now)
    result = {**deepcopy(result), "request":{"range":"1mo","interval":"1d","events":"splits"}}
    current = parse_regular_quote(symbol,result,now,profile=2)
    if (current["instrument_type"] != "INDEX" or result["meta"].get("currency") != "USD"
            or current["quote_timing"] != "completed_session" or current["session_date"] != periods["week_end"]):
        raise ValueError("Expected completed Friday benchmark session unavailable; holiday schedules require verification")
    stamps, closes = result.get("timestamp"), result.get("indicators",{}).get("quote",[{}])[0].get("close")
    if not isinstance(stamps,list) or not isinstance(closes,list) or not 2 <= len(stamps) <= 40 or len(stamps)!=len(closes):
        raise ValueError("Weekly daily-bar history is malformed or exceeds its bound")
    days = {}
    for epoch,value in zip(stamps,closes):
        at, close = source_time(epoch), finite_number(value)
        if at is None or at > now+timedelta(seconds=60):
            raise ValueError("Weekly history contains an invalid or future source clock")
        day = at.astimezone(NY).date().isoformat()
        if day in days:
            raise ValueError("Weekly history has duplicate session dates")
        days[day] = close
    first, last = days.get(periods["baseline_date"]), days.get(periods["week_end"])
    if first is None or last is None or first <= 0 or last <= 0:
        raise ValueError("Exact prior-Friday and ending-Friday closes required; no Monday or older substitution")
    evidence = source_evidence(result)
    return {"schema":1,"symbol":symbol,"source":"Yahoo chart; may be delayed","url":market_url(symbol),
            "observed":observed.isoformat(),"quote_asof":current["asof"],"baseline_date":periods["baseline_date"],
            "end_date":periods["week_end"],"baseline_close":first,"end_close":last,
            "weekly_percent":100*(last/first-1),"friday_percent":current["change_percent"],
            "basis":"dated Friday close versus the prior Friday close; price return, not total return",
            "quote_evidence":evidence,"source_sha256":digest(evidence)}


def checked_price(packet, periods, now):
    symbol = packet.get("symbol")
    if symbol not in BENCHMARKS or packet.get("url") != market_url(symbol):
        raise ValueError("Weekly market source identity changed")
    expected = price_packet(symbol,packet["quote_evidence"],packet["observed"],periods,now)
    if packet != expected:
        raise ValueError("Weekly return, date or original source evidence changed")
    return packet


def collect_prices(periods, now, fetch=None, *, force=False):
    fetch = fetch or (lambda url:feeds.fetch_url(url,force))
    def read(symbol):
        try:
            url = market_url(symbol); value = fetch(url)
            if value.get("status") != "ok":
                raise ValueError(value.get("error") or "Weekly chart unavailable")
            if value.get("final_url",value.get("url")) != url:
                raise ValueError("Weekly chart redirected outside its configured source")
            body = value.get("body")
            if not isinstance(body,str) or len(body.encode())>2_000_000:
                raise ValueError("Weekly chart response exceeds its bound")
            payload = json.loads(body); chart = payload.get("chart",{}); rows = chart.get("result")
            if chart.get("error") or not isinstance(rows,list) or len(rows)!=1:
                raise ValueError("Weekly chart result unavailable or ambiguous")
            proof = price_packet(symbol,rows[0],value.get("fetched_at_epoch"),periods,now)
            return {"symbol":symbol,"status":"available","proof":proof,"reason":"Exact two-Friday price basis verified"}
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError) as error:
            return {"symbol":symbol,"status":"limited","reason":str(error)[:180]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(read,BENCHMARKS))


def fact_schema(story):
    from src.intelligence import disclosure_details, defense_program, refinery_mix, treasury_financing
    family = disclosure_details.family(story)
    if family:return 12 if family == "maintenance" else 13
    if defense_program.applicable(story):return 10
    if refinery_mix.applicable(story):return 11
    if treasury_financing.document_kind(story):return 9
    from src.intelligence.energy_analysis import solar_storage_report
    if solar_storage_report(story):return None
    # Company earnings keep their specialized period/basis readers.
    if editor.materiality(story) in {"earnings","guidance"}:return None
    return 8


def admit_story(raw, text, observed, periods, now):
    from src.intelligence.original_disclosures import calendar_notice
    story = deepcopy(raw)
    for key in ("event_evidence","canonical_url","discovery_evidence","sec_filing","ipo","materiality"):
        story.pop(key,None)
    editor.canonical_url(story["url"])
    if not editor.primary_source(story) or story.get("official") is not True or calendar_notice(story.get("title","")):
        raise ValueError("A verified original business disclosure is required")
    published = clock(story.get("published")); observed = fresh(observed,now)
    if not clock(periods["evidence_start"]) <= published <= now or published > observed+timedelta(seconds=60):
        raise ValueError("Disclosure is outside this week's evidence window or its observation predates publication")
    if not isinstance(text,str) or not 80 <= len(text) <= 6000:
        raise ValueError("A bounded original article body is required")
    if story.get("publisher_symbol")=="NOC":
        from src.intelligence.northrop_newsroom import check_dateline
        check_dateline(text,published.isoformat())
    story.update(published=published.isoformat(),source_checked_at=observed.isoformat(),evidence_checked_at=observed.isoformat(),
                 source_excerpt=text,excerpt_scope="original release excerpt",disclosure_version=1)
    story["materiality"] = editor.materiality(story)
    # article_excerpt and the verified cache already produce admitted plain text.
    # Preserve that exact text; decoding it again can alter evidence sentences.
    story["event_evidence"] = analysis._from_admitted_text(story,text,"original release excerpt",schema=fact_schema(story))
    if len(story["event_evidence"]["facts"]) < 2:
        raise ValueError("Fewer than two concrete original-source fact fields were extracted")
    story["materiality"] = editor.materiality(story)
    if not story["materiality"]:
        raise ValueError("Original facts do not establish a supported business or policy topic")
    story["id"] = sha256((story["url"]+"|"+story["published"]).encode()).hexdigest()[:16]
    story["publication_label"] = "weekend update" if published.astimezone(NY).date().isoformat()>periods["week_end"] else "week disclosure"
    return {key:story[key] for key in ("id","kind","symbols","title","url","published","source","publisher_symbol","official",
        "source_checked_at","evidence_checked_at","source_excerpt","excerpt_scope","disclosure_version","materiality","event_evidence","publication_label")}


def checked_story(story, periods, now):
    expected = admit_story(story,story["source_excerpt"],story["evidence_checked_at"],periods,now)
    if story != expected:
        raise ValueError("Weekly disclosure facts, stage, dates or original proof changed")
    analysis.checked_evidence(story)
    return story


def collect_stories(raw, periods, now, fetch=None, *, force=False):
    from src.intelligence.original_disclosures import calendar_notice
    fetch = fetch or (lambda url:feeds.fetch_url(url,force,cache_result=False))
    eligible=[]; ledger=[]
    for value in raw[:1000]:
        try:
            if not editor.primary_source(value) or value.get("official") is not True or calendar_notice(value["title"]):continue
            at=clock(value.get("published"))
            if value.get("weekend_archive_lead") is not True:fresh(value.get("source_checked_at"),now)
            if not clock(periods["evidence_start"])<=at<=now:continue
            eligible.append(value)
        except (ValueError,TypeError,KeyError,AttributeError):continue
    def priority(row):
        observed=row.get("evidence_checked_at") or row.get("source_checked_at")
        body=row.get("source_excerpt","")
        if row.get("excerpt_scope")=="original release excerpt" and isinstance(body,str) and 80<=len(body)<=6000:
            try:
                fresh(observed,now)
            except (ValueError,TypeError):pass
            else:
                try:
                    proof=admit_story(row,body,observed,periods,now)
                    return (0,-min(len(proof["event_evidence"]["facts"]),6))
                except (ValueError,KeyError,TypeError,AttributeError):return (4,0)
        if row.get("weekend_archive_lead") is True:
            try:
                p=analysis.checked_evidence(row)
                if p["scope"]=="original release excerpt" and len(p["facts"])>=2:return (1,-min(len(p["facts"]),6))
            except (ValueError,KeyError,TypeError,AttributeError):pass
        try:
            if fact_schema(row) in {9,10,11,12,13}:return (2,0)
            return (3,not bool(editor.materiality({**row,"disclosure_version":1})))
        except (ValueError,KeyError,TypeError,AttributeError):return (4,0)
    # Local fact inspection does not consume a network read. Prefer useful
    # verified bodies and previously reviewed weekly disclosures over a headline.
    eligible.sort(key=lambda row:(*priority(row),-clock(row["published"]).timestamp(),row["url"]))
    # One first pass per publisher keeps a prolific feed from consuming the budget.
    first,extra,seen=[],[],set()
    for row in eligible:
        identity=row.get("publisher_symbol") or row["source"]
        (extra if identity in seen else first).append(row);seen.add(identity)
    unique={}
    for row in first+extra:unique.setdefault(row["url"],row)
    def read(row):
        log={"title":row["title"],"url":row["url"],"source":row["source"],"published":row["published"]}
        try:
            text=row.get("source_excerpt",""); observed=row.get("evidence_checked_at") or row.get("source_checked_at")
            use_cache=row.get("excerpt_scope")=="original release excerpt" and len(text)>=80
            if use_cache:
                try:fresh(observed,now)
                except (ValueError,TypeError):use_cache=False
            if not use_cache:
                value=fetch(row["url"])
                if value.get("status")!="ok":raise ValueError(value.get("error") or "Original body unavailable")
                if value.get("final_url",value.get("url"))!=row["url"]:raise ValueError("Original article redirected to another URL")
                body=value.get("body")
                if not isinstance(body,str) or len(body.encode())>2_000_000:raise ValueError("Original body response exceeds its bound")
                text=originals.article_excerpt(body,row["title"],row["published"],publisher=row["source"],url=row["url"])
                observed=value.get("fetched_at_epoch")
            proof=admit_story(row,text,observed,periods,now)
            log.update(status="admitted",facts=len(proof["event_evidence"]["facts"]),reason="Original body, weekly dates and concrete facts verified")
            if row.get("weekend_archive_lead") is True:
                log["reason"]="Prior edition supplied the lead; original body and observation verified for this build"
            return proof,log
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OverflowError) as error:
            log.update(status="held",facts=0,reason=str(error)[:180])
        return None,log
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(read,list(unique.values())[:MAX_BODY_READS]))
    return [proof for proof,_ in results if proof is not None],[log for _,log in results]


def raw_candidates(now):
    rows,issues=editor.cache_candidates(now,editor.editorial_symbols([]))
    from src.intelligence.news_editor_store import read_editions
    archived=[];seen=set();periods=window(now)
    try:
        for record in read_editions(limit=50):
            for raw in record.get("candidates",[])[:180]:
                try:
                    if raw.get("decision")!="selected" or not editor.primary_source(raw) or raw.get("official") is not True:continue
                    at=clock(raw["published"])
                    if not clock(periods["evidence_start"])<=at<=now or raw["url"] in seen:continue
                    profile=analysis.checked_evidence(raw)
                    if profile["scope"]!="original release excerpt" or len(profile["facts"])<2:continue
                    lead=deepcopy(raw)
                    lead.update(source_excerpt=profile["source_text"],excerpt_scope=profile["scope"],
                        evidence_checked_at=profile["observed_at"],weekend_archive_lead=True)
                    archived.append(lead);seen.add(raw["url"])
                except (ValueError,KeyError,TypeError,AttributeError):continue
    except (OSError,ValueError,TypeError,sqlite3.Error) as error:
        issues=[*issues,"Prior-edition weekly discovery unavailable ("+type(error).__name__+")"]
    issues=[f"Weekly discovery: {len(archived)} reviewed original disclosures from prior editions; stale observations require a new article read",*issues]
    return (archived+rows)[:1000],issues[:5]


def calendar_packet(raw, periods, now, snapshot=None):
    snapshot = calendar_context.read_snapshot(now) if snapshot is None else deepcopy(snapshot)
    result={"schema":1,"observed":"","macro":[],"company":[],"later":[],"issues":[]}
    start,end=date.fromisoformat(periods["next_start"]),date.fromisoformat(periods["next_end"])
    if snapshot is not None:
        try:
            checked=fresh(snapshot["checked_at"],now); result["observed"]=checked.isoformat()
            result["issues"]=list(snapshot.get("issues",[]))[:5]
            for row in snapshot.get("economic",[])[:2000]:
                try:
                    if row.get("time_status") not in {"verified","cached"}:continue
                    at=clock(row["event_at"])
                    if not start<=at.astimezone(NY).date()<=end:continue
                    if calendar_sources.SOURCE_URLS.get(row["publisher"])!=row.get("timing_url"):continue
                    if at.astimezone(NY).date().isoformat()!=row.get("source_date"):continue
                    if row["time_status"]=="cached":fresh(row["timing_checked_at"],now)
                    label=("Weekly jobless claims" if row["publisher"]=="DOL" and calendar_sources.category(row["eventName"],"DOL")=="claims" else row["eventName"])
                    result["macro"].append({"event":label,"at":at.isoformat(),"publisher":row["publisher"],
                        "url":row["timing_url"],"time_status":row["time_status"],"observed":checked.isoformat(),
                        "timing_observed":row.get("timing_checked_at") or checked.isoformat()})
                except (ValueError,KeyError,TypeError,AttributeError):continue
            if len({day["date"] for day in snapshot.get("days",[]) if start.isoformat()<=day["date"]<=end.isoformat()})<5:
                result["issues"].append("Snapshot does not cover all five days of the coming week")
        except (ValueError,TypeError,KeyError):
            result["issues"].append("Current publisher calendar snapshot unavailable")
    else:result["issues"].append("Current publisher calendar snapshot unavailable")
    result["macro"]=list({(row["event"],row["at"]):row for row in result["macro"]}.values())[:12]
    notices=company_schedule.notices(raw,now)
    for notice in notices[:20]:
        day=date.fromisoformat(notice["event_date"])
        if start<=day<=end:result["company"].append(notice)
        elif end<day<=end+timedelta(days=14):result["later"].append(notice)
    result["company"]=result["company"][:6];result["later"]=result["later"][:1]
    # Availability is a source-coverage statement, not a declaration of quiet days.
    result["coverage"]="limited"
    return result


def checked_calendar(packet, periods, now):
    if packet.get("schema")!=1 or packet.get("coverage")!="limited" or not isinstance(packet.get("issues"),list):
        raise ValueError("Weekend calendar coverage qualification changed")
    if packet.get("observed"):fresh(packet["observed"],now)
    start,end=date.fromisoformat(periods["next_start"]),date.fromisoformat(periods["next_end"])
    if not isinstance(packet.get("macro"),list) or len(packet["macro"])>12:raise ValueError("Calendar exceeds its bound")
    for row in packet["macro"]:
        at=clock(row["at"])
        if (not start<=at.astimezone(NY).date()<=end or row.get("time_status") not in {"verified","cached"}
                or calendar_sources.SOURCE_URLS.get(row.get("publisher"))!=row.get("url")
                or not isinstance(row.get("event"),str) or not 1<=len(row["event"])<=180):
            raise ValueError("Unverified or out-of-week calendar event")
        fresh(row["observed"],now);fresh(row["timing_observed"],now)
    for key,limit in (("company",6),("later",1)):
        if not isinstance(packet.get(key),list) or len(packet[key])>limit:raise ValueError("Issuer calendar exceeds its bound")
        for row in packet[key]:
            company_schedule.checked_notice(row,now)
            day=date.fromisoformat(row["event_date"])
            if not (start<=day<=end if key=="company" else end<day<=end+timedelta(days=14)):
                raise ValueError("Company event is in the wrong outlook horizon")
    return packet
