"""Bounded, dated five-minute bars. All changes share the prior US cash close."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import hashlib
import json
from urllib.parse import quote,urlsplit
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

from src.config.premarket import SYMBOLS
from src.utils.yahoo_quote import finite_number,source_time

NY=ZoneInfo("America/New_York")
PROVIDER="Yahoo chart; may be delayed; two price bars from one provider; premarket volume unverified"


def window(now):
    if now.tzinfo is None:raise ValueError("Premarket clock must be zoned")
    local=now.astimezone(NY)
    return local.weekday()<5 and 8*60<=local.hour*60+local.minute<9*60+30


def fetch(symbol, *, daily=False):
    if symbol not in SYMBOLS:raise ValueError("Instrument is outside the bounded premarket universe")
    query="range=1mo&interval=1d&includePrePost=false&events=div%2Csplits" if daily else "range=5d&interval=5m&includePrePost=true&events=div%2Csplits"
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+quote(symbol,safe="")+"?"+query
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0 SmartMoneyAI/1.6"}),timeout=8) as response:
        final=urlsplit(response.geturl())
        if final.scheme!="https" or final.hostname!="query1.finance.yahoo.com" or final.username or final.password:
            raise ValueError("Quote redirected outside its publisher")
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError("Quote response exceeds its limit")
    value=json.loads(raw);rows=value.get("chart",{}).get("result")
    if value.get("chart",{}).get("error") or not isinstance(rows,list) or len(rows)!=1:
        raise ValueError("Original chart result unavailable")
    return rows[0]


def periods(value):
    if isinstance(value,list):
        return [period for row in value for period in periods(row)]
    if isinstance(value,dict) and "start" in value and "end" in value:return [value]
    return []


def session(meta,now):
    regular=meta.get("currentTradingPeriod",{}).get("regular",{})
    start,end=source_time(regular.get("start")),source_time(regular.get("end"))
    if not start or not end or start.astimezone(NY).date()!=now.astimezone(NY).date():
        raise ValueError("Today's cash-session schedule is unavailable")
    if start.astimezone(NY).strftime("%H:%M")!="09:30" or not timedelta(hours=3)<=end-start<=timedelta(hours=7):
        raise ValueError("Cash-session hours are unverified")
    pre=meta.get("currentTradingPeriod",{}).get("pre",{})
    pre_start,pre_end=source_time(pre.get("start")),source_time(pre.get("end"))
    if not pre_start or pre_end!=start or pre_start.astimezone(NY).date()!=start.astimezone(NY).date():
        raise ValueError("Premarket session metadata unavailable")
    past=[]
    for row in periods(meta.get("tradingPeriods",{}).get("regular",[]) if isinstance(meta.get("tradingPeriods"),dict) else []):
        a,b=source_time(row.get("start")),source_time(row.get("end"))
        if a and b and a<b<start and b.astimezone(NY).date()<start.astimezone(NY).date():past.append((a,b))
    if not past:raise ValueError("Dated prior regular-session schedule unavailable")
    before,close=max(past,key=lambda row:row[1])
    if not timedelta(hours=3)<=close-before<=timedelta(hours=7) or (start-close).days>7:
        raise ValueError("Prior regular-session schedule is invalid or too old")
    return {"open":start.isoformat(),"end":end.isoformat(),"pre":pre_start.isoformat(),
            "previous_open":before.isoformat(),"previous_close":close.isoformat(),"day":start.astimezone(NY).date().isoformat()}


def packet(symbol,result,now,config,anchor=None):
    if not window(now):raise ValueError("Outside the premarket check window")
    meta=result.get("meta",{});future=symbol in {"NQ=F","ES=F"}
    if symbol not in SYMBOLS or meta.get("symbol")!=symbol or meta.get("currency")!="USD":
        raise ValueError("Quote identity or currency mismatch")
    if meta.get("dataGranularity")!="5m" or meta.get("instrumentType") not in ({"FUTURE"} if future else {"ETF"} if symbol in {"SPY","QQQ","SMH"} else {"EQUITY"}):
        raise ValueError("Quote type or five-minute granularity mismatch")
    if future:
        if anchor is None:raise ValueError("Futures require the verified US cash-session anchor")
        local=now.astimezone(NY)
        if local.month in {3,6,9,12} and 8<=local.day<=22:
            raise ValueError("Continuous futures roll window; use cash ETF evidence")
        bounds=anchor
        regular=meta.get("currentTradingPeriod",{}).get("regular",{})
        a,b=source_time(regular.get("start")),source_time(regular.get("end"))
        if not a or not b or not a<=now<b:raise ValueError("Futures trading-session metadata unavailable")
    else:
        bounds=session(meta,now)
        if anchor and bounds!=anchor:raise ValueError("Instrument cash-session dates differ from SPY")
    opened,pre,closed=(datetime.fromisoformat(bounds[k]) for k in ("open","pre","previous_close"))
    if not pre<=now<opened:raise ValueError("Price is outside today's premarket session")
    for kind in ("splits","dividends"):
        for row in result.get("events",{}).get(kind,{}).values():
            at=source_time(row.get("date"))
            if at is None or (at>=closed and at.astimezone(NY).date()<=now.astimezone(NY).date()):
                raise ValueError("Split/distribution requires a corporate-action check")
    quotes=result.get("indicators",{}).get("quote",[])
    if len(quotes)!=1:raise ValueError("One original quote series is required")
    times=result.get("timestamp",[]);closes=quotes[0].get("close",[]);volumes=quotes[0].get("volume",[])
    if not len(times)==len(closes)==len(volumes) or len(times)>5000:raise ValueError("Incomplete or oversized dated quote series")
    bars=[];seen=set()
    for epoch,raw,volume in zip(times,closes,volumes):
        at,price,vol=source_time(epoch),finite_number(raw),finite_number(volume)
        if at is None or at in seen:raise ValueError("Invalid or duplicate quote clock")
        seen.add(at)
        bars.append((at,price,vol))
    baseline=[row for row in bars if row[0]==closed-timedelta(minutes=5)]
    if len(baseline)!=1 or baseline[0][1] is None or baseline[0][1]<=0:
        raise ValueError("Exact prior regular-session closing bar unavailable")
    current=sorted([row for row in bars if pre<=row[0] and row[0]+timedelta(minutes=5)<=min(now,opened)
                    and row[1] is not None and row[1]>0])
    if len(current)<2:raise ValueError("Two dated premarket price bars unavailable")
    first,last=current[-2:]
    if last[0]-first[0]!=timedelta(minutes=5) or (now-(last[0]+timedelta(minutes=5))).total_seconds()>config["max_age"]:
        raise ValueError("Premarket bars are stale or nonconsecutive")
    changes=[round(100*(row[1]/baseline[0][1]-1),6) for row in (first,last)]
    if max(map(abs,changes))>40 or abs(changes[1]-changes[0])>2:
        raise ValueError("Unusual or inconsistent gap needs another price/corporate-action check")
    if future and max(map(abs,changes))>10:raise ValueError("Unusual continuous-futures gap withheld")
    # Retain the exact admitted bars and schedules, not later bars or undated metadata prices.
    chosen=[baseline[0],first,last]
    evidence={"meta":{k:meta[k] for k in ("symbol","currency","instrumentType","dataGranularity","currentTradingPeriod","tradingPeriods","shortName") if k in meta},
              "timestamp":[int(row[0].timestamp()) for row in chosen],
              "indicators":{"quote":[{"close":[row[1] for row in chosen],"volume":[row[2] for row in chosen]}]},
              "events":result.get("events",{})}
    return {"symbol":symbol,"change":changes[1],"prior_bar_change":changes[0],"price":last[1],"baseline_price":baseline[0][1],
            "asof":(last[0]+timedelta(minutes=5)).isoformat(),"baseline_at":closed.isoformat(),"session":bounds,
            "basis":"versus the prior US regular-session closing bar; futures are not settlement returns",
            "source":PROVIDER,"url":"https://finance.yahoo.com/quote/"+quote(symbol,safe="")+"/","evidence":evidence}


def collect(now,config,fetcher=fetch):
    if not window(now):return {},["Outside the premarket check window; no quote requests"]
    values={};issues=[]
    def read(symbol):
        try:return symbol,fetcher(symbol),None
        except Exception as error:return symbol,None,type(error).__name__
    with ThreadPoolExecutor(max_workers=4) as pool:
        for symbol,value,error in pool.map(read,SYMBOLS):
            if error:issues.append(symbol+": "+error)
            else:values[symbol]=value
    quotes={}
    try:quotes["SPY"]=packet("SPY",values.get("SPY",{}),now,config)
    except (ValueError,KeyError,TypeError,OverflowError) as error:return {},issues+["SPY session anchor: "+str(error)]
    for symbol,value in values.items():
        if symbol=="SPY":continue
        try:quotes[symbol]=packet(symbol,value,now,config,quotes["SPY"]["session"])
        except (ValueError,KeyError,TypeError,OverflowError) as error:issues.append(symbol+": "+str(error))
    return quotes,issues
