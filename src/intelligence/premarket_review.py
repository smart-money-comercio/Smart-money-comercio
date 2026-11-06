"""Observed regular-session stress after the warning, including recovery days."""

from datetime import datetime,timedelta
from src.intelligence.premarket_sources import NY,fetch
from src.intelligence.premarket_risk import LEVELS
from src.intelligence import premarket_store as store
from src.utils.yahoo_quote import parse_regular_quote,finite_number,source_time

TARGETS={"SPY":-1.5,"QQQ":-2,"SMH":-3}


def observe(now,fetcher=fetch):
    local=now.astimezone(NY)
    if local.weekday()>4 or local.hour*60+local.minute<16*60+20:raise ValueError("Outcome review waits until 16:20 Eastern")
    values={}
    for symbol,threshold in TARGETS.items():
        raw=fetcher(symbol,daily=True);row=parse_regular_quote(symbol,raw,now)
        if raw.get("meta",{}).get("dataGranularity")!="1d":raise ValueError("Daily outcome granularity unavailable")
        for kind in ("splits","dividends"):
            for event in raw.get("events",{}).get(kind,{}).values():
                at=source_time(event.get("date"))
                if at is None or at.astimezone(NY).date()==local.date():raise ValueError("Outcome needs split/distribution review")
        end=source_time(raw.get("meta",{}).get("currentTradingPeriod",{}).get("regular",{}).get("end"))
        if row["instrument_type"]!="ETF" or row["session_date"]!=local.date().isoformat() or not end or now<end+timedelta(minutes=15):
            raise ValueError("Completed same-day ETF outcome unavailable")
        bars=raw.get("indicators",{}).get("quote",[{}])[0];lows=[]
        for epoch,low,close in zip(raw.get("timestamp",[]),bars.get("low",[]),bars.get("close",[])):
            at=source_time(epoch);number=finite_number(low)
            if (at and at.astimezone(NY).date()==local.date() and number is not None and 0<number<=row["price"]
                    and finite_number(close) is not None and abs(close-row["price"])<=.01):lows.append(number)
        if len(lows)!=1:raise ValueError("Unambiguous regular-session low unavailable")
        worst=100*(lows[0]/row["previous_close"]-1)
        values[symbol]={"close_change":row["change_percent"],"worst_change":worst,"threshold":threshold,"stress":worst<=threshold,
                        "asof":row["asof"],"evidence":raw}
    return {"schema":1,"day":local.date().isoformat(),"observed_at":now.isoformat(),"values":values,
            "stress":any(row["stress"] for row in values.values()),"basis":"Regular-session intraday low versus prior close; fixed operational thresholds, not investment returns"}


def checked_outcome(value):
    now=datetime.fromisoformat(value["observed_at"])
    expected=observe(now,lambda symbol,**kwargs:value["values"][symbol]["evidence"])
    if value!=expected:raise ValueError("Outcome differs from its dated source evidence")
    return value


def report():
    rows=store.history(180);outcomes=store.outcomes();latest={}
    for row in rows:
        prior=latest.setdefault(row["day"],row)
        if LEVELS[row["assessment"]["level"]]>LEVELS[prior["assessment"]["level"]]:latest[row["day"]]=row
    counts={"stress followed warning":0,"warning without threshold breach":0,"missed threshold breach":0,"no warning / no breach":0,"limited input coverage":0,"no premarket record":0,"awaiting outcome":0}
    for day in sorted(set(latest)|set(outcomes)):
        row=latest.get(day)
        outcome=outcomes.get(day)
        if outcome is not None:
            try:checked_outcome(outcome)
            except (ValueError,KeyError,TypeError):outcome=None
        if row is None:label="no premarket record"
        elif outcome is None:label="awaiting outcome"
        elif row["assessment"]["level"] in {"LIMITED","OUTSIDE WINDOW"}:label="limited input coverage"
        else:
            warned=LEVELS[row["assessment"]["level"]]>0
            label=("stress followed warning" if warned else "missed threshold breach") if outcome["stress"] else ("warning without threshold breach" if warned else "no warning / no breach")
        counts[label]+=1
    lines=["Premarket Outcome Review","One count per day: retain any qualifying pre-open warning; otherwise use the latest recorded slot.",
           "Stress target: SPY intraday -1.5%, QQQ -2%, or SMH -3%, versus prior regular close."]
    lines.extend(f"{label}: {number}" for label,number in counts.items())
    lines.extend(["Warning counts describe recorded decisions. Delivery receipts remain separate.",
                  "No validated prediction accuracy is inferred. Thresholds and false alarms need observation over many sessions."])
    return "\n".join(lines)
