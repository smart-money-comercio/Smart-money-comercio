"""Independent, source-bound weekly research edition and review-only media draft."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import re
from threading import RLock

from src.intelligence import weekend_inputs as evidence, weekend_store as store, weekend_theme as themes
from src.intelligence import company_schedule
from src.intelligence.daily_brief_analysis import NAMES
from src.utils.market_quote_source import BENCHMARKS
from src.utils.speech_text import normalize
from src.reports import weekend_narration

LOCK = RLock()
MAX_CHARACTERS = 10000


def text_hash(value):
    return sha256(value.encode("utf-8")).hexdigest()


def day_label(value):
    at = date.fromisoformat(value)
    return f"{at:%B} {at.day}, {at.year}"


def change(value):
    return ("rose " if value > 0 else "fell " if value < 0 else "was unchanged at ")+f"{abs(value):.2f} percent"


def weekly_read(prices, periods):
    available = [row["proof"] for row in prices if row["status"] == "available"]
    text = (f"The completed week ran from {day_label(periods['week_start'])} through {day_label(periods['week_end'])}. "
            f"Weekly price returns compare the {day_label(periods['baseline_date'])} close with the {day_label(periods['week_end'])} close. ")
    if available:
        text += "Over that week, "+"; ".join(BENCHMARKS[row["symbol"]]+" "+change(row["weekly_percent"]) for row in available)+". "
        text += "Friday alone: "+"; ".join(BENCHMARKS[row["symbol"]]+" "+change(row["friday_percent"]) for row in available)+". "
        if all(row["weekly_percent"]<0 and row["friday_percent"]>0 for row in available):
            text += "Friday's rebound left these benchmarks below their prior-week closes. "
    if len(available)<3:
        text += f"Weekly benchmark coverage is incomplete: {len(available)} of three verified. "
    text += "These are price returns, excluding dividends. Market prices describe the outcome; the disclosures below provide separate business evidence."
    return text


def calendar_read(packet, periods):
    days = {}
    for row in packet["macro"]:
        at = evidence.clock(row["at"]).astimezone(evidence.NY)
        days.setdefault(at.date().isoformat(),[]).append(f"{row['event']} at {at:%I:%M %p %Z}, according to {row['publisher']}")
    for row in packet["company"]:
        days.setdefault(row["event_date"],[]).append(company_schedule.narration(row,evidence.NY,NAMES))
    lines=[]
    for offset in range(5):
        day = date.fromisoformat(periods["next_start"])+timedelta(days=offset)
        rows = days.get(day.isoformat(),[])
        lines.append(f"{day:%A}, {day:%B} {day.day}: "+("; ".join(rows)+"." if rows else "No publisher-verified entry in this edition's evidence."))
    lines.append("Calendar coverage is limited. Missing entries indicate missing verified coverage, rather than an absence of scheduled events. Estimated earnings dates are excluded. Labor and demand releases can test the operating backdrop; issuer results and guidance can test company sales, margins and spending.")
    return "\n".join(lines)


def source_map(inputs, selected):
    sources={}
    for row in inputs["prices"]:
        if row["status"] != "available":continue
        proof=row["proof"]
        sources["market_"+row["symbol"]]=[{"url":proof["url"],"publisher":proof["source"],
            "session_date":proof["end_date"],"baseline_date":proof["baseline_date"],
            "verified_at":proof["observed"],"quote_asof":proof["quote_asof"],"source_sha256":proof["source_sha256"]}]
    for row in selected:
        sources["story_"+row["id"]]=[{"url":row["url"],"publisher":row["source"],"published_at":row["published"],
            "verified_at":row["evidence_checked_at"],"source_sha256":row["event_evidence"]["source_sha256"]}]
    for index,row in enumerate(inputs["calendar"]["macro"]):
        sources["calendar_"+str(index)]=[{"url":row["url"],"publisher":row["publisher"],"event_at":row["at"],
            "verified_at":row["timing_observed"],"kind":"publisher calendar"}]
    for key in ("company","later"):
        for index,row in enumerate(inputs["calendar"][key]):
            source=row["source"]
            sources[key+"_"+str(index)]=[{"url":source["url"],"publisher":source["source"],
                "published_at":source["published"],"verified_at":source["source_checked_at"],"event_date":row["event_date"]}]
    return sources


def content(inputs, theme):
    from src.intelligence import weekend_business
    business_version = weekend_business.revision(inputs)
    narration_revision=weekend_narration.revision(inputs)
    periods=inputs["window"]
    selected=[row for row in inputs["stories"] if theme and row["id"] in theme["story_ids"]]
    sources=source_map(inputs,selected)
    sections=[]
    def add(heading,narration,source_ids=(),bullets=()):
        sections.append({"heading":heading,"narration":narration,"bullets":list(bullets)[:3],"source_ids":list(source_ids)})
    add("Week in perspective",weekly_read(inputs["prices"],periods),[key for key in sources if key.startswith("market_")])
    if theme:
        facts=[]
        for row in selected:
            stamp=evidence.clock(row["published"]).astimezone(evidence.NY)
            label=("This weekend update" if row["publication_label"]=="weekend update" else "The disclosure") if narration_revision>=2 else "This "+row["publication_label"]
            facts.append(weekend_business.dated_summary(row, stamp) if business_version else
                         themes.summary(row)+f" {label} was published {stamp:%B} {stamp.day}.")
        add(theme["title"],theme["question"]+("\n\n" if business_version else "\n\nOriginal disclosures:\n")+"\n\n".join(facts),
            ["story_"+row["id"] for row in selected],[theme["question"]])
        argument = (weekend_business.discussion(selected, theme, inputs["business_analysis"]) if business_version else
                    "Analyst interpretation: "+theme["case"]+"\n\n"+
                    "\n\n".join(view["name"]+": "+view["why"]+" "+view["watch"] for view in map(themes.business,selected)))
        add("Business interpretation", argument,
            ["story_"+row["id"] for row in selected])
    else:
        add("Theme under review","No weekly investment theme qualified from verified original bodies with at least two concrete fact fields. This edition remains a review copy; the missing evidence does not establish that business conditions were unchanged.")
    add("Coming week: "+day_label(periods["next_start"])+" to "+day_label(periods["next_end"]),
        calendar_read(inputs["calendar"],periods),[key for key in sources if key.startswith(("calendar_","company_"))])
    if inputs["calendar"]["later"]:
        add("Beyond the coming week","Later horizon, outside the coming Monday-to-Friday window: "+
            " ".join(company_schedule.narration(row,evidence.NY,NAMES) for row in inputs["calendar"]["later"]),
            [key for key in sources if key.startswith("later_")])
    if theme:
        scenarios = (weekend_business.conditions(selected, theme, inputs["business_analysis"]) if business_version else
                     "Conditional scenarios, not forecasts or assigned probabilities.\n\n"+
                     "\n\n".join(theme[key] for key in ("base","stronger","weaker")))
        add("Conditions to watch", scenarios, ["story_"+row["id"] for row in selected])
    context = ("The written outlook includes the sources and observation times. Check new disclosures as the week develops. Research only. Not financial advice."
               if business_version else "This outlook separates dated disclosures, analyst interpretation and conditional scenarios. It does not attribute stock moves to those disclosures. Check new original evidence before changing the investment case. Research only. Not financial advice.")
    add("Research context", context)
    header=("Smart Money Weekend Outlook\n"+f"Completed week: {periods['week_start']} to {periods['week_end']}\n"+
            f"Ahead: {periods['next_start']} to {periods['next_end']}\n"+f"Generated: {inputs['generated_at']}\n")
    references=[]
    for key,rows in sources.items():
        for row in rows:
            detail=(" | Published: "+row["published_at"]) if row.get("published_at") else ""
            references.append(f"{key} — {row['publisher']}{detail} | Observed: {row['verified_at']}\n{row['url']}")
    report=header+"\n\n"+"\n\n".join(row["heading"]+"\n"+row["narration"] for row in sections)
    report+="\n\nSources and observation clocks\n"+("\n\n".join(references) or "No qualified evidence references.")
    narrated=[]
    for row in sections:
        text=row["narration"]
        if business_version and row["heading"] == "Week in perspective":
            text = weekend_business.spoken_week(text, periods)
        if narration_revision>=2:
            if row["heading"].startswith("Coming week:"):text=weekend_narration.calendar(inputs["calendar"],periods)
            spoken=weekend_narration.spoken(text)
        else:spoken=normalize(text,brand_names=True,agency_names=True,disclosure_names=True)
        narrated.append({**row,"narration":spoken})
    if narration_revision>=2:narrated[0]["narration"]="Smart Money Weekend Outlook.\n\n"+narrated[0]["narration"]
    script=("" if narration_revision>=2 else "Smart Money Weekend Outlook.\n\n")+"\n\n".join(row["narration"] for row in narrated)
    words=len(re.findall(r"\b[\w]+(?:['-][\w]+)*\b",script))
    quality={"status":"PASS" if 300<=words<=1200 else "CHECK","words":words,"estimated_seconds":round(words*60/160,1),"words_per_minute":160}
    voice={"schema":2,"input_sha256":evidence.digest(inputs),"script":script,"script_sha256":text_hash(script),
        "segments":narrated,"sources":sources,"quality":quality}
    if narration_revision>=2:voice["narration_revision"]=narration_revision
    return report,voice


def assess(inputs,theme,report,voice):
    checks={"weekly_prices":sum(row["status"]=="available" for row in inputs["prices"])>=2,
        "original_theme":bool(theme),"report_bound":len(report)<=MAX_CHARACTERS,
        "narration":voice["quality"]["status"]=="PASS","calendar_scope":True}
    if inputs.get("business_version") == 1:
        checks["business_interpretation"] = True
    return {"status":"PASS" if all(checks.values()) else "CHECK","checks":checks,
        "notes":["Calendar coverage is limited; unknown days remain qualified."]}


def assemble(inputs):
    from src.intelligence import weekend_business
    theme=themes.choose(inputs["stories"])
    business_version = weekend_business.revision(inputs)
    if business_version:
        selected = [row for row in inputs["stories"] if theme and row["id"] in theme["story_ids"]]
        weekend_business.checked(selected, inputs["business_analysis"])
    report,voice=content(inputs,theme)
    record={"schema":1,"edition_type":"weekend_outlook","rules_version":31 if business_version else 30,"generated_at":inputs["generated_at"],
        "inputs":deepcopy(inputs),"input_sha256":evidence.digest(inputs),"theme":theme,"report_text":report,
        "report_sha256":text_hash(report),"voiceover":voice,"quality":assess(inputs,theme,report,voice)}
    record["id"]=store.identity(record)
    return record


def checked(record,now=None,*,require_publishable=False):
    try:
        if (record.get("schema")!=1 or record.get("edition_type")!="weekend_outlook" or record.get("rules_version") not in {30, 31}
                or record.get("id")!=store.identity(record)):
            raise ValueError("Weekend edition identity or schema changed")
        at=evidence.clock(record["generated_at"]);inputs=record["inputs"]
        if inputs["generated_at"]!=record["generated_at"] or inputs["window"]!=evidence.window(at):
            raise ValueError("Weekend edition dates changed")
        if (len(inputs["prices"])!=3 or {row["symbol"] for row in inputs["prices"]}!=set(BENCHMARKS)
                or len(inputs["stories"])>6 or len(inputs["ledger"])>6
                or len({row["id"] for row in inputs["stories"]})!=len(inputs["stories"])):
            raise ValueError("Weekend evidence exceeds its bound or has duplicate sources")
        for row in inputs["prices"]:
            if row["status"]=="available":evidence.checked_price(row["proof"],inputs["window"],at)
            elif row["status"]!="limited":raise ValueError("Weekly source status changed")
            if row["status"]=="available" and row["symbol"]!=row["proof"]["symbol"]:raise ValueError("Weekly source identity changed")
        for row in inputs["stories"]:evidence.checked_story(row,inputs["window"],at)
        evidence.checked_calendar(inputs["calendar"],inputs["window"],at)
        if assemble(inputs)!=record:raise ValueError("Weekend facts, interpretation, report or narration changed")
        if require_publishable:
            now=now or datetime.now(timezone.utc)
            periods=evidence.window(now)
            if periods["week_end"]!=inputs["window"]["week_end"] or not -60<=(now-at).total_seconds()<=28800:
                raise ValueError("Weekend edition is stale; run /weekend refresh")
            for row in inputs["prices"]:
                if row["status"]=="available":evidence.fresh(row["proof"]["observed"],now)
            for row in inputs["stories"]:evidence.fresh(row["evidence_checked_at"],now)
            evidence.checked_calendar(inputs["calendar"],periods,now)
            if record["quality"]["status"]!="PASS":raise ValueError("Weekend edition is CHECK; review /weekendstatus before export")
        return record
    except (KeyError,TypeError,AttributeError,IndexError,OverflowError) as error:
        raise ValueError("Weekend evidence is missing or malformed") from error


def build(now=None,*,force=False,raw=None,market_fetch=None,body_fetch=None,calendar_snapshot=None,persist=True):
    now=now or datetime.now(timezone.utc)
    periods=evidence.window(now)
    now=now.astimezone(timezone.utc)
    with LOCK:
        if not force and raw is None and market_fetch is None and body_fetch is None:
            prior=store.latest()
            if (prior and prior.get("inputs",{}).get("narration_revision")==weekend_narration.REVISION
                    and prior["inputs"].get("business_version") == 1):
                try:
                    checked(prior,now,require_publishable=True)
                    if (now-evidence.clock(prior["generated_at"])).total_seconds()<=1800:return prior
                except ValueError:pass
        rows,issues=evidence.raw_candidates(now) if raw is None else (deepcopy(raw),[])
        with ThreadPoolExecutor(max_workers=2) as pool:
            prices=pool.submit(evidence.collect_prices,periods,now,market_fetch,force=force)
            stories=pool.submit(evidence.collect_stories,rows,periods,now,body_fetch,force=force)
            found,ledger=stories.result()
            inputs={"generated_at":now.isoformat(),"narration_revision":weekend_narration.REVISION,"window":periods,"prices":prices.result(),"stories":found,
                "ledger":ledger,"calendar":evidence.calendar_packet(rows,periods,now,calendar_snapshot),"source_issues":issues}
        from src.intelligence import weekend_business
        theme = themes.choose(inputs["stories"])
        selected = [row for row in inputs["stories"] if theme and row["id"] in theme["story_ids"]]
        inputs.update(business_version=1, business_analysis=weekend_business.analyze(selected))
        record=assemble(inputs);checked(record)
        if persist:store.save(record)
        return record


def status(record,now=None):
    checked(record);now=now or datetime.now(timezone.utc)
    try:
        checked(record,now,require_publishable=True);readiness="Current evidence; ready for review-only export"
    except ValueError as error:readiness=str(error)
    inputs=record["inputs"];theme=record["theme"]
    lines=["Smart Money Weekend Outlook Quality",f"Status: {record['quality']['status']} | Editorial rules: {record['rules_version']}",
        f"Edition: {record['id']} | Built: {record['generated_at']}",readiness,
        f"Weekly basis: {inputs['window']['baseline_date']} close to {inputs['window']['week_end']} close",
        f"Coming week: {inputs['window']['next_start']} to {inputs['window']['next_end']}"]
    for row in inputs["prices"]:
        detail=(f"weekly {row['proof']['weekly_percent']:+.2f}%; Friday {row['proof']['friday_percent']:+.2f}%; observed {row['proof']['observed']}"
                if row["status"]=="available" else row["reason"])
        lines.append(BENCHMARKS[row["symbol"]]+": "+row["status"]+" — "+detail)
    selected=theme["story_ids"] if theme else []
    lines += ["Theme: "+(theme["title"] if theme else "No qualified original theme"),
        f"Original bodies: {len(inputs['stories'])} admitted / {len(inputs['ledger'])} reviewed; {len(selected)} selected",
        "Concrete fact fields: "+str(sum(len(row["event_evidence"]["facts"]) for row in inputs["stories"] if row["id"] in selected))]
    for row in inputs["ledger"]:lines.append(row["status"].upper()+" — "+row["title"]+": "+row["reason"])
    lines += [f"Calendar: {len(inputs['calendar']['macro'])} verified macro / {len(inputs['calendar']['company'])} issuer notices; {len(inputs['calendar']['later'])} later-horizon notices. Coverage limited.",
        "Voiceover: "+str(record["voiceover"]["quality"]["words"])+" words; about "+str(record["voiceover"]["quality"]["estimated_seconds"])+" seconds at 160 words/minute",
        "Narration revision: "+str(record["voiceover"].get("narration_revision",1)),
        "Checks: "+"; ".join(key+": "+("PASS" if value else "CHECK") for key,value in record["quality"]["checks"].items())]
    if inputs.get("business_version") == 1:
        analysis = inputs["business_analysis"]
        lines.append("Business interpretation: " + str(len(analysis["reviews"])) + " source-bound reviews; cross-company comparison "
                     + ("available" if analysis["comparison"] else "requires distinct business stages"))
    lines += ["Coverage: "+str(value) for value in inputs["source_issues"]+inputs["calendar"]["issues"]]
    return "\n".join(lines)


def episode(record,now=None):
    checked(record,now,require_publishable=True)
    voice=record["voiceover"];periods=record["inputs"]["window"]
    packet={"title":"Smart Money Weekend Outlook | Week of "+periods["next_start"],"date":evidence.clock(record["generated_at"]).astimezone(evidence.NY).date().isoformat(),
        "edition_type":"weekend_outlook","week_start":periods["week_start"],"week_end":periods["week_end"],
        "next_week_start":periods["next_start"],"next_week_end":periods["next_end"],
        "description":"Source-reviewed weekly research and conditional business scenarios. AI narration and illustrative graphics require human review. Research only. Not financial advice.",
        "mode":"draft_review_required","review_required":True,"contains_synthetic_media":True,
        "segments":deepcopy(voice["segments"]),"sources":deepcopy(voice["sources"]),"bot_edition_id":record["id"],
        "bot_report_sha256":record["report_sha256"],"bot_generated_at":record["generated_at"],
        "voiceover_sha256":voice["script_sha256"],"voiceover_schema":2,"voiceover_quality":deepcopy(voice["quality"])}
    if voice.get("narration_revision"):packet["weekend_narration_revision"]=voice["narration_revision"]
    return packet
