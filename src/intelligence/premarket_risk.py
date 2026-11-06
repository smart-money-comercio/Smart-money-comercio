"""Versioned pre-open observations, graded rules and explicit coverage limits."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json

from src.config.premarket import CHIPS,SYMBOLS
from src.intelligence.premarket_sources import NY,packet,window
from src.intelligence.premarket_disclosures import risk_sentences
from src.intelligence.special_alert_sources import timestamp
from src.utils.yahoo_quote import finite_number

LEVELS={"NONE":0,"WATCH":1,"ELEVATED":2,"SEVERE":3,"LIMITED":0,"OUTSIDE WINDOW":0}


def digest(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def assess(quotes,documents,now,config):
    if (set(config)!={"enabled","max_age","chip_gap","tech_gap","broad_gap"} or type(config["enabled"]) is not bool
            or type(config["max_age"]) is not int or not 300<=config["max_age"]<=900
            or any(finite_number(config[key]) is None or not low<=config[key]<=high for key,low,high in
                   (("chip_gap",2,10),("tech_gap",.5,3),("broad_gap",.5,3)))
            or not isinstance(quotes,dict) or not set(quotes)<=set(SYMBOLS) or not isinstance(documents,list) or len(documents)>6):
        raise ValueError("Unknown premarket configuration or input bounds")
    if not window(now):return {"level":"OUTSIDE WINDOW","signals":[],"scope":"unavailable","coverage":"No premarket assessment outside 08:00–09:30 America/New_York"}
    if "SPY" not in quotes or "QQQ" not in quotes:
        return {"level":"LIMITED","signals":[],"scope":"unavailable","coverage":"Fresh SPY and QQQ observations are required; missing data is not a calm reading"}
    anchor=packet("SPY",quotes["SPY"]["evidence"],now,config)
    values={}
    for symbol,row in quotes.items():
        checked=packet(symbol,row["evidence"],now,config,anchor["session"] if symbol!="SPY" else None)
        if checked!=row:raise ValueError("Displayed premarket quote does not match its source bars")
        values[symbol]=max(row["change"],row["prior_bar_change"])
    signals=[]
    spy,qqq=values["SPY"],values["QQQ"]
    chip_available=[s for s in CHIPS if s in values];weak=[s for s in chip_available if values[s]<=-config["chip_gap"]]
    if "NQ=F" in values and "ES=F" in values and values["NQ=F"]<=-.5 and values["NQ=F"]-values["ES=F"]<=-.35:
        signals.append({"id":"futures","text":"Nasdaq-100 futures lag S&P futures while falling at least 0.5% since the prior US cash close"})
    if qqq<=-config["tech_gap"] and qqq-spy<=-.35 or values.get("SMH",0)<=-1.5:
        signals.append({"id":"sector","text":"Technology/semiconductor ETFs show premarket pressure"})
    if spy<=-config["broad_gap"] and qqq<=-1:
        signals.append({"id":"broad","text":"Both broad-market and technology ETFs show premarket pressure"})
    if len(weak)>=3:
        signals.append({"id":"chips","text":f"{len(weak)} of {len(CHIPS)} tracked chip companies are down at least {config['chip_gap']:g}%; {len(chip_available)} have usable quotes"})
    supporting=[]
    from src.intelligence.premarket_disclosures import checked_document
    for row in documents:
        checked_document(row)
        published,observed=timestamp(row.get("published")),timestamp(row.get("observed"))
        if (not published or not observed or not datetime.fromisoformat(anchor["session"]["previous_close"])<=published<=observed<=now
                or (now-published).total_seconds()>86400 or (now-observed).total_seconds()>21600
                or sha256(row.get("text","").encode()).hexdigest()!=row.get("sha256")):
            raise ValueError("Original disclosure clock or text proof is invalid")
        if row["symbol"] in values and values[row["symbol"]]<=-config["chip_gap"] and risk_sentences(row["text"]):supporting.append(row["symbol"])
    if supporting:signals.append({"id":"disclosure","text":"Original disclosures contain business-risk facts for falling companies: "+", ".join(sorted(set(supporting)))})
    price_signals=[row for row in signals if row["id"]!="disclosure"]
    level="NONE" if not price_signals else "WATCH"
    if not price_signals and (len(chip_available)<3 or "SMH" not in quotes):level="LIMITED"
    if len(price_signals)>=2 or price_signals and supporting:level="ELEVATED"
    if spy<=-1.5 and qqq<=-2 and (values.get("SMH",0)<=-3 or sum(values[s]<=-5 for s in chip_available)>=3):level="SEVERE"
    scope="broad market and technology" if any(row["id"]=="broad" for row in signals) else "semiconductors / AI infrastructure" if signals else "tracked instruments"
    return {"level":level,"signals":signals,"scope":scope,
            "coverage":f"{len(quotes)}/{len(SYMBOLS)} usable quotes; {len(chip_available)}/{len(CHIPS)} chip companies. Premarket volume is unverified. Single-provider, correlated observations do not establish a probability or cause."}


def snapshot(quotes,documents,issues,now,config,slot):
    if slot not in {"08:45","09:15","preview"}:raise ValueError("Unknown premarket slot")
    value={"schema":1,"day":now.astimezone(NY).date().isoformat(),"slot":slot,"observed_at":now.isoformat(),
           "config":deepcopy(config),"quotes":deepcopy(quotes),"documents":deepcopy(documents),"issues":list(issues),
           "assessment":assess(quotes,documents,now,config)}
    value["id"]=digest(value);return value


def checked(value):
    original=deepcopy(value);identity=original.pop("id",None)
    if type(original.get("schema")) is not int or original["schema"]!=1 or digest(original)!=identity:raise ValueError("Premarket snapshot hash mismatch")
    now=timestamp(value.get("observed_at"))
    if not now or value["day"]!=now.astimezone(NY).date().isoformat() or value["assessment"]!=assess(value["quotes"],value["documents"],now,value["config"]):
        raise ValueError("Premarket assessment differs from its frozen evidence")
    if value["slot"] not in {"preview","08:45","09:15"}:raise ValueError("Unknown premarket slot")
    if value["slot"]!="preview":
        due=now.astimezone(NY).replace(hour=int(value["slot"][:2]),minute=int(value["slot"][3:]),second=0,microsecond=0)
        if not 0<=(now-due).total_seconds()<600:raise ValueError("Scheduled snapshot does not match its slot clock")
    return value


def render(value):
    checked(value);a=value["assessment"];at=timestamp(value["observed_at"]).astimezone(NY)
    lines=["Smart Money Premarket Risk",at.strftime("%Y-%m-%d %H:%M %Z")+" · "+value["slot"],
           "Risk: "+a["level"]+" · Scope: "+a["scope"],a["coverage"]]
    lines.extend("• "+row["text"] for row in a["signals"])
    for symbol in ("SPY","QQQ","SMH","NQ=F","ES=F",*CHIPS):
        row=value["quotes"].get(symbol)
        if row:lines.append(f"{symbol}: {row['change']:+.2f}% · bar through "+timestamp(row["asof"]).astimezone(NY).strftime("%H:%M %Z"))
    if value["quotes"]:lines.append("Source: Yahoo chart; may be delayed. Change basis: prior US regular-session closing bar; futures figures are not exchange-settlement returns. https://finance.yahoo.com/quote/SPY/")
    for row in value["documents"][:1]:
        clock_label="SEC accepted: " if row["source"]=="SEC EDGAR original earnings exhibit" else "Published: "
        lines.extend(["Original disclosure — "+row["symbol"]+": "+row["title"],clock_label+row["published"],
                      *("Disclosed fact: "+fact["evidence"] for fact in risk_sentences(row["text"])[:1]),row["url"]])
    if value["issues"]:lines.append("Coverage limits: "+"; ".join(value["issues"])[:400])
    lines.extend(["Watch: whether weakness spreads or eases after the open, and whether original company guidance changes the business outlook.",
                  "This is an observed-risk warning. The later direction and size of the market move remain uncertain.",
                  "Built assessment; delivery receipts are recorded separately. /premarket history · /premarket review",
                  "Research only. Not financial advice."])
    return "\n".join(lines)
