"""Original cached disclosures plus a bounded Qualcomm SEC earnings read."""

from datetime import datetime,timezone
from hashlib import sha256
import json
import os
import re

from src.intelligence.special_alert_sources import timestamp
from src.intelligence.alphabet_earnings import ExhibitLinks,visible,_read
from src.intelligence.sec_research import Identity,entity_key,location
from src.intelligence.premarket_sources import NY

QCOM_SUBMISSIONS="https://data.sec.gov/submissions/CIK0000804328.json"
QCOM_NAMES={"qualcommincorporated","qualcommincde"}


def checked_document(row):
    from src.intelligence.special_alert_sources import company_url
    if not 1<=len(row.get("title",""))<=300 or not 80<=len(row.get("text",""))<=20000 or len(row.get("url",""))>800:
        raise ValueError("Original disclosure exceeds its bounds")
    if row.get("source")=="SEC EDGAR original earnings exhibit":
        if row.get("symbol")!="QCOM" or not re.fullmatch(r"\d{10}-\d{2}-\d{6}",row.get("accession","")):
            raise ValueError("SEC disclosure identity unavailable")
        identity=("804328",row["accession"].replace("-",""))
        if location(row["url"])[:2]!=identity or location(row["filing_url"])[:2]!=identity:
            raise ValueError("SEC disclosure escaped its issuer/accession")
    elif not company_url(row.get("symbol",""),row.get("url","")):
        raise ValueError("Disclosure publisher does not match its company")
    if sha256(row["text"].encode()).hexdigest()!=row.get("sha256"):raise ValueError("Disclosure text hash differs")
    return row


def risk_sentences(text):
    from src.intelligence.original_disclosures import sentences
    found=[]
    for sentence in sentences(text):
        if len(sentence)>650 or re.search(r"\b(?:could|might|if|risks?|hypothetical|previously|not)\b",sentence,re.I):continue
        if re.search(r"\b(?:revenue|sales|orders|demand) (?:fell|declined|decreased) (?:by )?\d+(?:\.\d+)?%",sentence,re.I):
            found.append({"field":"reported_business_decline","evidence":sentence})
        elif re.search(r"\b(?:industry|company|we) (?:is |are )?experiencing (?:a )?(?:broad-based )?increase in input costs\b",sentence,re.I):
            found.append({"field":"input_cost_pressure","evidence":sentence})
        elif re.search(r"\b(?:we|company) (?:have |has )?(?:cut|lowered|reduced|withdrawn) (?:our |its |the )?(?:revenue |earnings |sales )?(?:guidance|outlook)\b",sentence,re.I):
            found.append({"field":"disclosed_outlook_reduction","evidence":sentence})
    return found[:3]


def qualcomm(now,fetch):
    """At most submissions + one 8-K + its unique 99.1; no search or old fallback."""
    payload,first=_read(QCOM_SUBMISSIONS,fetch,now);metadata=json.loads(payload["body"])
    if str(int(metadata.get("cik",0)))!="804328" or entity_key(metadata.get("name","")) not in QCOM_NAMES or "QCOM" not in metadata.get("tickers",[]):
        raise ValueError("Qualcomm SEC issuer mismatch")
    recent=metadata.get("filings",{}).get("recent",{});keys=("accessionNumber","form","acceptanceDateTime","primaryDocument","items")
    if any(not isinstance(recent.get(k),list) or len(recent[k])>2000 for k in keys) or len({len(recent[k]) for k in keys})!=1:
        raise ValueError("SEC filing columns are malformed")
    rows=[dict(zip(keys,values)) for values in zip(*(recent[k] for k in keys)) if values[1] in {"8-K","8-K/A"} and "2.02" in {v.strip() for v in str(values[4]).split(",")}]
    if any(timestamp(row["acceptanceDateTime"]) is None for row in rows):raise ValueError("SEC acceptance clock is unverified")
    rows.sort(key=lambda row:timestamp(row["acceptanceDateTime"]),reverse=True)
    if not rows:return None
    row=rows[0];published=timestamp(row["acceptanceDateTime"])
    if published>now:raise ValueError("SEC earnings filing is future-dated")
    if (now-published).total_seconds()>86400:return None
    if row["form"]!="8-K" or not re.fullmatch(r"\d{10}-\d{2}-\d{6}",row["accessionNumber"]):
        raise ValueError("Amended or malformed results require review")
    accession=row["accessionNumber"].replace("-","")
    primary=f"https://www.sec.gov/Archives/edgar/data/804328/{accession}/{row['primaryDocument']}"
    if location(primary)[:2]!=("804328",accession):raise ValueError("SEC primary document identity mismatch")
    report,second=_read(primary,fetch,now);identity=Identity();identity.feed(report["body"])
    values=identity.values
    if ({str(int(v)) for v in values.get("EntityCentralIndexKey",[]) }!={"804328"}
            or len(values.get("EntityRegistrantName",[]))!=1 or not {entity_key(v) for v in values.get("EntityRegistrantName",[])}<=QCOM_NAMES
            or values.get("TradingSymbol")!={"QCOM"} or values.get("DocumentType")!={"8-K"}):
        raise ValueError("SEC 8-K does not identify Qualcomm")
    text=visible(report["body"]);item=re.search(r"\bItem\s+2\.02\b",text,re.I)
    item_text=re.split(r"\bItem\s+\d+\.\d+\b",text[item.end():],maxsplit=1,flags=re.I)[0] if item else ""
    if not re.search(r"press release",item_text,re.I) or "99.1" not in item_text:raise ValueError("SEC results item does not bind its exhibit")
    links=ExhibitLinks(primary);links.feed(report["body"]);urls=sorted(set(links.links))
    if len(urls)!=1 or location(urls[0])[:2]!=("804328",accession) or urls[0]==primary:raise ValueError("Unique earnings exhibit unavailable")
    document,third=_read(urls[0],fetch,now);body=visible(document["body"])
    title=re.search(r"Qualcomm Announces (?:First|Second|Third|Fourth) Quarter(?: and Fiscal 20\d{2})? (?:20\d{2} )?Results",body[:1500],re.I)
    date=re.search(r"SAN DIEGO\s*[-–—]\s*([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})\s*[-–—]\s*Qualcomm Incorporated",body[:3000])
    if not title or not date or datetime.strptime(date[1],"%B %d, %Y").date()!=published.astimezone(NY).date():
        raise ValueError("Earnings exhibit heading, issuer and release date do not bind the filing")
    return {"symbol":"QCOM","title":title[0],"text":body[:20000],"published":published.isoformat(),"release_date":datetime.strptime(date[1],"%B %d, %Y").date().isoformat(),
            "observed":datetime.fromtimestamp(min(first,second,third),timezone.utc).isoformat(),"url":urls[0],"source":"SEC EDGAR original earnings exhibit",
            "sha256":sha256(body[:20000].encode()).hexdigest(),"filing_url":primary,"accession":row["accessionNumber"]}


def collect(now,previous_close,fetcher=None):
    from src.intelligence import news_editor as editor,news_live_sources as feeds
    found=[];issues=[]
    try:
        candidates,_=editor.cache_candidates(now,[])
        for row in candidates:
            if row.get("kind")!="company" or not editor.primary_source(row) or row.get("excerpt_scope")!="original release excerpt":continue
            published=timestamp(row.get("published"));observed=timestamp(row.get("evidence_checked_at") or row.get("source_checked_at"))
            if not published or not observed or not previous_close<=published<=observed<=now or (now-published).total_seconds()>86400 or (now-observed).total_seconds()>21600:continue
            text=row.get("source_excerpt","")
            if risk_sentences(text):found.append({"symbol":row["publisher_symbol"],"title":row["title"],"text":text,
                "published":published.isoformat(),"observed":observed.isoformat(),"url":row["url"],"source":row["source"],"sha256":sha256(text.encode()).hexdigest()})
    except (OSError,ValueError,KeyError,TypeError):issues.append("Cached original-disclosure coverage unavailable")
    if not os.getenv("SEC_USER_AGENT","").strip():
        issues.append("QCOM original earnings: SEC_USER_AGENT not configured; no SEC requests")
    else:
        try:
            fetcher=fetcher or (lambda url:feeds.fetch_url(url,force_refresh=True,cache_result=False,user_agent=os.environ["SEC_USER_AGENT"]))
            row=qualcomm(now,fetcher)
            if row and previous_close<=timestamp(row["published"])<=now and risk_sentences(row["text"]):found.append(row)
        except Exception as error:issues.append("QCOM original earnings limited: "+type(error).__name__)
    return found[:6],issues
