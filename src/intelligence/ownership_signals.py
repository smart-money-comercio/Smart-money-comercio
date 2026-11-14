"""Source-linked Form 4 clusters and Schedule 13D ownership changes."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import os
import re
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

from src.insiders import insider_data as sec
from src.intelligence import transaction_cache as cache
from src.intelligence.transaction_disclosures import (
    CACHE_AGE, NY, SYMBOL, day, filing_path, label, scope_observations, sec_fields, short_value,
)


KINDS = {"insider_cluster", "ownership_stake"}
ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
CIK = re.compile(r"[0-9]{1,10}")
FORMS = {"SC 13D": "SCHEDULE 13D", "SC 13D/A": "SCHEDULE 13D/A",
         "SCHEDULE 13D": "SCHEDULE 13D", "SCHEDULE 13D/A": "SCHEDULE 13D/A"}
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/"
FILING_DAYS = 7
CLUSTER_DAYS = 30
MIN_PURCHASE = 100_000
MIN_CHANGE = Decimal("1")
COMMON_EQUITY = re.compile(r"\b(?:common (?:shares|stock)|ordinary (?:shares|stock))\b", re.I)


def enabled():
    return os.getenv("SEC_OWNERSHIP_ALERTS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def normalized_cik(value):
    return value.zfill(10) if isinstance(value, str) and CIK.fullmatch(value) and int(value) else ""


def filing_base(cik, accession):
    return f"{ARCHIVE}{int(cik)}/{accession.replace('-', '')}/"


def ownership_rows(payload):
    rows = payload.get("ownership_filings", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) and len(rows) <= 300 else []


def checked_issuers(payload, now):
    checks = payload.get("ownership_checks", {})
    if not isinstance(checks, dict) or len(checks) > 256:
        return {}
    return {cik: at for cik, at in checks.items() if cik and normalized_cik(cik) == cik
            and type(at) in (int, float) and 0 < at <= now.timestamp()}


def retain(rows, today):
    retained = {(row["cik"], row["accession"]): row for row in rows if isinstance(row.get("cik"), str)
                and isinstance(row.get("accession"), str) and isinstance(row.get("filed"), str)
                and (today - timedelta(days=365)).isoformat() <= row["filed"] <= today.isoformat()}
    return sorted(retained.values(), key=lambda row: (row["filed"], row["accession"]), reverse=True)[:300]


def source_filings(payload, today):
    recent = payload["filings"]["recent"]
    values = []
    for index, form in enumerate(recent["form"]):
        if form not in FORMS:
            continue
        accession = recent["accessionNumber"][index]
        filed = day(recent["filingDate"][index])
        if (today - timedelta(days=365) <= filed <= today and isinstance(accession, str) and ACCESSION.fullmatch(accession)):
            values.append((filed.isoformat(), accession, FORMS[form], recent["primaryDocument"][index], index))
    return sorted(values, key=lambda row: (row[0], -row[-1]), reverse=True)


def normalized_space(value, limit):
    return " ".join(value.split())[:limit].strip() if isinstance(value, str) else ""


def disclosed_number(value, ceiling):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,13}(?:\.[0-9]{1,8})?", value):
        raise ValueError("Missing Schedule 13D ownership figure")
    number = Decimal(value)
    if number > ceiling:
        raise ValueError("Schedule 13D ownership figure outside range")
    return format(number.normalize(), "f")


def parse_ownership(raw, cik, ticker, filing, url):
    filed, accession, form, _, _ = filing
    if len(raw) > 1_000_000 or re.search(rb"<!DOCTYPE|<!ENTITY", raw, re.I):
        raise ValueError("Invalid Schedule 13D document")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("Unreadable Schedule 13D XML") from error
    if root.tag != "{http://www.sec.gov/edgar/schedule13D}edgarSubmission":
        raise ValueError("Expected structured Schedule 13D XML")
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    header = root.find("./formData/coverPageHeader")
    if header is None or normalized_cik(header.findtext("./issuerInfo/issuerCIK")) != cik:
        raise ValueError("Schedule 13D subject issuer does not match the SEC index")
    if root.findtext("./headerData/submissionType") != form:
        raise ValueError("Schedule 13D form does not match the SEC index")
    reported = datetime.strptime(header.findtext("dateOfEvent", ""), "%m/%d/%Y").date()
    if reported > day(filed):
        raise ValueError("Schedule 13D event date is after its filing")
    class_title = normalized_space(header.findtext("securitiesClassTitle"), 180)
    cusips = sorted({node.text.strip().upper() for path in ("./issuerInfo/issuerCUSIP", "./issuerInfo/issuerCusips/issuerCusipNumber")
                     for node in header.findall(path) if node.text and re.fullmatch(r"[A-Za-z0-9]{9}", node.text.strip())})
    if not class_title:
        raise ValueError("Schedule 13D security class unavailable")
    owners = {}
    for node in root.findall("./formData/reportingPersons/reportingPersonInfo"):
        name = normalized_space(node.findtext("reportingPersonName"), 110)
        person = normalized_cik(node.findtext("reportingPersonCIK"))
        if not name:
            continue
        try:
            percent = disclosed_number(node.findtext("percentOfClass"), 100)
            shares = disclosed_number(node.findtext("aggregateAmountOwned"), 10**12)
        except ValueError:
            continue
        key = person or name.casefold()
        value = {"name": name, "cik": person, "percent": percent, "shares": shares}
        if key in owners and owners[key] != value:
            raise ValueError("Conflicting Schedule 13D reporting-person rows")
        owners[key] = value
    if not owners or len(owners) > 50:
        raise ValueError("Schedule 13D ownership rows unavailable")
    purpose = normalized_space(root.findtext("./formData/items1To7/item4/transactionPurpose"), 6001)
    if len(purpose) > 6000:
        purpose = ""
    company = normalized_space(header.findtext("./issuerInfo/issuerName"), 120) or ticker
    return {"cik": cik, "ticker": ticker, "company": company, "accession": accession, "form": form, "filed": filed,
            "event_date": reported.isoformat(), "class": class_title, "cusips": cusips[:20], "owners": list(owners.values()),
            "purpose": purpose, "prior_13g": header.findtext("previouslyFiledFlag", "").lower() in {"true", "1"},
            "url": url, "sha256": sha256(raw).hexdigest()}


def read_issuer(payload, cik, ticker, saved, reader, now):
    today = now.astimezone(NY).date()
    filings = source_filings(payload, today)
    known = {row["accession"]: row for row in saved if row.get("cik") == cik and safe_stake(row)}
    active = [row for row in filings if (today - day(row[0])).days < FILING_DAYS]
    wanted = {row[1] for row in active}
    for index, filing in enumerate(filings[:-1]):
        if (today - day(filing[0])).days < FILING_DAYS and filing[2].endswith("/A"):
            wanted.add(filings[index + 1][1])
    for index, filing in enumerate(filings):
        filed, accession, _, document, _ = filing
        if accession not in wanted:
            continue
        prior_accession = filings[index + 1][1] if index + 1 < len(filings) else ""
        if accession in known:
            known[accession]["prior_accession"] = prior_accession
            continue
        if not isinstance(document, str) or not re.fullmatch(r"(?:xsl[A-Za-z0-9_]+/)?[A-Za-z0-9_.-]+\.xml", document) or ".." in document:
            if (today - day(filed)).days < FILING_DAYS:
                raise ValueError("Structured Schedule 13D document unavailable")
            continue
        base = filing_base(cik, accession)
        path = document.rsplit("/", 1)[-1]
        urls = list(dict.fromkeys((base + path, filing_base(accession[:10], accession) + path)))
        problem = None
        for url in urls:
            try:
                raw = reader.bytes(url, same_host=True, max_bytes=1_000_000)
            except HTTPError as error:
                if error.code != 404:
                    raise
                problem = error
                continue
            row = parse_ownership(raw, cik, ticker, filing, url)
            break
        else:
            if problem is not None and (today - day(filed)).days < FILING_DAYS:
                raise problem
            continue
        row["prior_accession"] = prior_accession
        saved.append(row)


def event(kind, key, ticker, filed, evidence):
    # SEC submissions give a filing date here. Keep it as a date in the copy.
    clock = datetime.combine(day(filed), datetime.min.time(), NY)
    return {"kind": kind, "key": kind + ":" + key, "level": 1, "symbols": [ticker], "published": clock.astimezone(timezone.utc).isoformat(),
            "expires": (clock + timedelta(days=FILING_DAYS)).timestamp(), "ttl": 31 * 86400, "evidence": evidence}


def purchase_clusters(payload, now):
    today = now.astimezone(NY).date()
    observations = scope_observations("sec", payload, now)
    grouped = defaultdict(list)
    amendments = defaultdict(set)
    for raw in cache.rows(payload):
        try:
            fields = sec_fields(raw)
            ticker = raw.get("ticker")
            if not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker):
                continue
            traded, filed = day(raw.get("transaction_date")), day(fields["filing_date"])
            cik = normalized_cik(fields["cik"])
            observation = observations.get(cik)
            if not observation or now.timestamp() - observation["at"] > CACHE_AGE.total_seconds():
                continue
            if not traded <= filed <= datetime.fromtimestamp(observation["at"], NY).date() or not 0 <= (today - traded).days < CLUSTER_DAYS:
                continue
        except (ValueError, TypeError):
            continue
        person = fields["insider_name"].casefold()
        owner = normalized_cik(raw.get("reporting_owner_cik"))
        if fields["form"] == "4/A":
            amendments[cik].update({person, owner} - {""})
        security = normalized_space(raw.get("security_title"), 160).casefold()
        if (fields["transaction_code"] != "P" or fields["rule_10b5_1"] or raw.get("joint_reporting")
                or not COMMON_EQUITY.search(security)):
            continue
        # Records created before the owner CIK was retained still have the filed owner name.
        grouped[(cik, ticker, security)].append({"owner": fields["insider_name"], "owner_cik": owner,
                                                 "trade_date": traded.isoformat(), "filed": filed.isoformat(),
                                                 "amount": round(fields["shares"] * fields["price"], 2),
                                                 "accession": fields["accession"], "url": fields["url"]})
    alerts = []
    for (cik, ticker, _), purchases in grouped.items():
        owners, used = [], set()
        ordered = sorted(purchases, key=lambda row: (row["filed"], row["trade_date"], row["amount"], row["accession"]), reverse=True)
        for row in ordered:
            identities = {row["owner"].casefold(), row["accession"]} | ({row["owner_cik"]} if row["owner_cik"] else set())
            if row["amount"] < MIN_PURCHASE or identities & (used | amendments[cik]):
                continue
            used.update(identities)
            owners.append(row)
            if len(owners) == 2:
                break
        if len(owners) != 2:
            continue
        latest = max(row["filed"] for row in owners)
        if (today - day(latest)).days >= FILING_DAYS:
            continue
        identity = ":".join(sorted(row["accession"] for row in owners))
        alerts.append(event("insider_cluster", cik + ":" + identity, ticker, latest, {"ticker": ticker, "purchases": owners}))
    return alerts


def safe_stake(row):
    try:
        accession, cik, ticker = row["accession"], row["cik"], row["ticker"]
        if not ACCESSION.fullmatch(accession) or normalized_cik(cik) != cik or not SYMBOL.fullmatch(ticker):
            return False
        path = filing_path(row["url"], "www.sec.gov")
        if not any(row["url"].startswith(filing_base(owner, accession)) for owner in (cik, accession[:10])) or not path.endswith(".xml"):
            return False
        owners, cusips = row["owners"], row["cusips"]
        if not isinstance(owners, list) or not 0 < len(owners) <= 50 or not isinstance(cusips, list) or len(cusips) > 20:
            return False
        if any(not re.fullmatch(r"[A-Z0-9]{9}", value) for value in cusips):
            return False
        if not all(isinstance(row[key], str) and len(row[key]) <= limit for key, limit in (("purpose", 6000), ("class", 180), ("company", 120))):
            return False
        if not row["class"] or type(row["prior_13g"]) is not bool:
            return False
        for owner in owners:
            if not isinstance(owner["name"], str) or not 0 < len(owner["name"]) <= 110 or normalized_cik(owner["cik"]) != owner["cik"]:
                return False
            disclosed_number(owner["percent"], 100)
            disclosed_number(owner["shares"], 10**12)
        prior = row.get("prior_accession", "")
        return (row["form"] in FORMS.values() and day(row["event_date"]) <= day(row["filed"])
                and (prior == "" or bool(ACCESSION.fullmatch(prior))) and bool(re.fullmatch(r"[0-9a-f]{64}", row["sha256"])))
    except (KeyError, ValueError, TypeError):
        return False


def comparable(current, previous):
    return (current["cik"] == previous["cik"] and current["ticker"] == previous["ticker"]
            and len(current["cusips"]) == 1 and current["cusips"] == previous["cusips"]
            and current["class"].casefold() == previous["class"].casefold()
            and current.get("prior_accession") == previous["accession"]
            and current["filed"] >= previous["filed"] and current["event_date"] >= previous["event_date"])


def stake_changes(payload, now):
    today = now.astimezone(NY).date()
    observations = checked_issuers(payload, now)
    grouped = defaultdict(list)
    for row in ownership_rows(payload):
        if safe_stake(row) and day(row["filed"]) <= today:
            grouped[row["cik"]].append(row)
    alerts = []
    for cik, rows in grouped.items():
        observed = observations.get(cik, 0)
        if now.timestamp() - observed > CACHE_AGE.total_seconds():
            continue
        rows.sort(key=lambda row: (row["filed"], row["event_date"], row["accession"]), reverse=True)
        current = rows[0]
        if (today - day(current["filed"])).days >= FILING_DAYS:
            continue
        if any(row["filed"] == current["filed"] and row["accession"] != current.get("prior_accession") for row in rows[1:]):
            continue
        old = {}
        if current["form"].endswith("/A") and len(rows) > 1 and comparable(current, rows[1]):
            old = {owner["cik"]: owner for owner in rows[1]["owners"] if owner["cik"]}
        for owner in sorted(current["owners"], key=lambda row: Decimal(row["percent"]), reverse=True):
            percent = Decimal(owner["percent"])
            prior = old.get(owner["cik"])
            if current["form"].endswith("/A"):
                if not prior:
                    continue
                prior_percent = Decimal(prior["percent"])
                if max(percent, prior_percent) <= 5 or abs(percent - prior_percent) < MIN_CHANGE:
                    continue
            elif percent <= 5 or Decimal(owner["shares"]) <= 0:
                continue
            proof = {"current": current, "owner": owner, "previous": rows[1] if prior else None, "prior_owner": prior}
            alerts.append(event("ownership_stake", current["accession"], current["ticker"], current["filed"], proof))
            break
    return alerts


def event_fact(alert):
    evidence = alert["evidence"]
    if alert["kind"] == "insider_cluster":
        names = " and ".join(row["owner"] for row in evidence["purchases"])
        return f"{evidence['ticker']} — {names} reported direct purchases within 30 days in separate SEC Form 4 filings."
    current, owner = evidence["current"], evidence["owner"]
    prefix = f"{current['ticker']} — {owner['name']} reported {owner['percent']}% beneficial ownership of the disclosed class"
    prior = evidence["prior_owner"]
    if prior:
        direction = "up" if Decimal(owner["percent"]) > Decimal(prior["percent"]) else "down"
        prefix += f", {direction} from {prior['percent']}% in the prior matched filing"
    form = "Schedule 13D amendment" if current["form"].endswith("/A") else "Schedule 13D"
    return prefix + f" in a {form} filed {current['filed']}."


def alert_text(alert):
    evidence = alert["evidence"]
    if alert["kind"] == "insider_cluster":
        lines = ["SEC Form 4 · Insider Purchase Cluster", event_fact(alert)]
        for row in evidence["purchases"]:
            lines.extend([f"{row['owner']} — about {short_value(row['amount'])} on {row['trade_date']}, filed {row['filed']}.", row["url"]])
        return "\n".join(lines + ["The filings report purchases. Follow subsequent filings and company results for context."])
    current = evidence["current"]
    lines = ["SEC Schedule 13D · Beneficial Ownership", event_fact(alert),
             f"Reported event date {current['event_date']} · {current['class']}", current["url"]]
    shares = Decimal(evidence["owner"]["shares"])
    lines.append(f"Shares reported: {shares:,}")
    if evidence["previous"]:
        lines.extend(["Prior matched Schedule 13D", evidence["previous"]["url"]])
    if current["prior_13g"]:
        lines.append("The filer indicated a prior Schedule 13G.")
    if current["purpose"]:
        complete = re.match(r"^.{1,280}?[.!?](?=\s|$)", current["purpose"])
        if complete and len(current["purpose"]) <= 280:
            lines.append("Item 4 excerpt — " + current["purpose"])
        else:
            lines.append("Item 4 describes the filer’s stated purpose in the linked filing.")
    return "\n".join(lines + ["A reported stake can change through transactions or changes in shares outstanding."])


def analyst_review(alert):
    if alert["kind"] == "insider_cluster":
        return "Interpretation: Compare the purchases with the next company results and any later filings."
    return "Interpretation: Check the stated purpose in Item 4 and whether the share count changed alongside the reported percentage."


def collect(now):
    if not enabled():
        return [], "disabled"
    payload, revision = cache.read(sec.CACHE_FILE)
    if not payload or payload.get("source") != "SEC Form 4":
        return [], "cache unavailable" if revision is not None else "waiting for the disclosure refresh"
    alerts = purchase_clusters(payload, now) + stake_changes(payload, now)
    for alert in alerts:
        alert["text"] = alert_text(alert)
        alert["agent_review"] = analyst_review(alert)
    checks = sum(now.timestamp() - at <= CACHE_AGE.total_seconds() for at in checked_issuers(payload, now).values())
    form4 = sum(now.timestamp() - row["at"] <= CACHE_AGE.total_seconds() for row in scope_observations("sec", payload, now).values())
    return sorted(alerts, key=lambda row: row["published"], reverse=True), f"Form 4: {form4} issuers · 13D: {checks} issuers with recent source checks"
