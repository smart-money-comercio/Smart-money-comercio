"""Follow one monthly inflation and household spending question from schedule to release."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import unescape
import logging
import re
import sqlite3

from src.intelligence import calendar_source_cache as cache, news_editor_store as store
from src.intelligence.calendar_sources import BEA_URL, NY
from src.intelligence.stockanalysis_source import TableParser

QUESTION = "Inflation and spending watch"
ANSWER = "Inflation and spending results"
PENDING = "Inflation and spending update"
SOURCE_ID = "bea_income_outlays"
WINDOW = timedelta(days=7)
PREVIEW = timedelta(hours=72)
TITLE = "Personal Income and Outlays"
UNIT = "Percent change from preceding month"
LABELS = ("PCE price index", "Real PCE")
NUMBER = re.compile(r"[+-]?\d{1,2}\.\d")
EMBARGO = re.compile(r"embargoed until release at (\d{1,2}:\d{2})\s*([ap])\.?m\.?\s+(EST|EDT),?\s+"
                     r"(Monday|Tuesday|Wednesday|Thursday|Friday),?\s+([A-Z][a-z]+ \d{1,2}, 20\d{2})", re.I)


def visible(html):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def period_for(row):
    if row["url"] != BEA_URL or row["publisher"] != "BEA" or row["category"] != "pce":
        raise ValueError("Expected the national BEA release schedule")
    due = cache.timestamp(row["at"]).astimezone(NY)
    name = row["name"].strip()
    if name == TITLE:
        # For generic schedule titles this month is a lookup hint only. The
        # release heading, column labels and publication clock must also match.
        return (due.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    if not name.startswith(TITLE + ", "):
        raise ValueError("Unrecognized BEA release title")
    period = datetime.strptime(name.removeprefix(TITLE + ", "), "%B %Y").date()
    if not 0 < (due.date() - period).days <= 150:
        raise ValueError("Invalid BEA reference period")
    return period


def release_url(period, due):
    # The URL's first year is the publication year, including January releases.
    return f"https://www.bea.gov/news/{due.astimezone(NY).year}/personal-income-and-outlays-{period:%B-%Y}".lower()


def capture(payload, schedule, now):
    period = period_for(schedule)
    due = cache.timestamp(schedule["at"])
    url = release_url(period, due)
    if not isinstance(payload, dict) or payload.get("status") != "ok" or payload.get("url") != url or payload.get("final_url") != url:
        raise ValueError("Expected the original BEA release")
    observed = datetime.fromtimestamp(payload["fetched_at_epoch"], timezone.utc).replace(microsecond=0)
    html = re.sub(r"<!--.*?-->|<(script|style)\b[^>]*>.*?</\1\s*>", "", payload["body"], flags=re.I | re.S)
    titles = [visible(body) for _, body in re.findall(r"<(h[1-3])\b[^>]*>(.*?)</\1\s*>", html, re.I | re.S)]
    title = f"{TITLE}, {period:%B %Y}"
    if title not in titles:
        raise ValueError("Wrong BEA reference month")
    matches = EMBARGO.findall(visible(html))
    if len(set(matches)) != 1:
        raise ValueError("Ambiguous BEA publication clock")
    clock, am_pm, zone, weekday, day = matches[0]
    published = datetime.strptime(day + " " + clock + " " + am_pm.upper() + "M", "%B %d, %Y %I:%M %p").replace(tzinfo=NY)
    if published.tzname() != zone.upper() or published.strftime("%A").lower() != weekday.lower():
        raise ValueError("Inconsistent publication timezone or weekday")
    previous = (period - timedelta(days=1)).strftime("%B")
    columns = [previous, period.strftime("%B")]
    tables = []
    for table in re.finditer(r"<table\b[^>]*>.*?</table\s*>", html, re.I | re.S):
        prefix = visible(html[:table.start()])[-180:]
        heading = visible(table[0]).split(columns[0], 1)[0]
        if not re.search(r"\b" + UNIT + r"\s*\]?\s*$", prefix + " " + heading, re.I):
            continue
        parser = TableParser()
        parser.feed(table[0])
        if len(parser.tables) != 1:
            continue
        headers = [i for i, row in enumerate(parser.tables[0]) if [s for s in row if s] == columns]
        if len(headers) != 1:
            continue
        rows = parser.tables[0][headers[0]+1:]
        pairs = []
        for label in LABELS:
            found = [r[1:] for r in rows if r and r[0] == label]
            if len(found) != 1 or len(found[0]) != 2:
                break
            pairs.append([v.replace("−", "-") for v in found[0]])
        if len(pairs) == 2:
            core = [r[1:] for r in rows if r and r[0] in {"PCE price index excluding food and energy", "PCE price index, excluding food and energy"}]
            if len(core) == 1 and len(core[0]) == 2:
                values = [cell.replace("−", "-") for cell in core[0]]
                if all(NUMBER.fullmatch(cell) for cell in values):
                    pairs.append(values)
            tables.append(pairs)
    if len(tables) != 1:
        raise ValueError("No unique official monthly price and spending table")
    result = {"url": url, "title": title, "unit": UNIT, "columns": columns, "published": published.isoformat(),
              "observed": observed.isoformat(), "inflation": tables[0][0], "real_spending": tables[0][1]}
    if len(tables[0]) == 3:
        result["core_inflation"] = tables[0][2]
    check_result(result, schedule, now)
    return result


def check_result(result, row, now):
    period = period_for(row)
    due = cache.timestamp(row["at"])
    published = cache.timestamp(result["published"])
    seen = cache.timestamp(result["observed"])
    if (result["url"] != release_url(period, due) or result["title"] != f"{TITLE}, {period:%B %Y}"
            or result["columns"] != [(period - timedelta(days=1)).strftime("%B"), period.strftime("%B")]
            or result["unit"] != UNIT or not due <= published <= seen <= now or now - due > WINDOW):
        raise ValueError("BEA release identity, monthly columns or evidence clocks changed")
    for pair in [result["inflation"], result["real_spending"]] + ([result["core_inflation"]] if "core_inflation" in result else []):
        if not isinstance(pair, list) or len(pair) != 2 or any(not NUMBER.fullmatch(v) for v in pair):
            raise ValueError("Invalid month-over-month percentage")


def core_read(result):
    before, current = map(Decimal, result["core_inflation"])
    if before == current:
        return f"core PCE inflation held steady at {current}% month over month."
    verb = "slowed" if current < before else "picked up"
    return f"core PCE inflation {verb} from {before}% to {current}% month over month."


def core_opening(item, now, version=4):
    checked_text(item, now)
    if item["phase"] != "answer" or not item.get("prior_edition"):
        raise ValueError("Core inflation lead requires an answered, delivered question")
    if version >= 5:
        result = item["result"]
        month = period_for(item["schedule"]).strftime("%B")
        before, current = map(Decimal, result["inflation"])
        core_before, core = map(Decimal, result["core_inflation"])
        direction = "fell" if current < before else "rose"
        headline = (f"The monthly inflation rate {direction} from {before}% to {current}% in {month}."
                    if current != before else f"The monthly inflation rate held at {current}% in {month}.")
        if core != core_before:
            direction = "fell" if core < core_before else "rose"
            return f"{headline} Excluding food and energy, the rate {direction} from {core_before}% to {core}%."
        if core == 0:
            return f"{headline} Excluding food and energy, prices were flat for a second straight month."
        return (f"{headline} Excluding food and energy, prices {'rose' if core > 0 else 'fell'} "
                f"{abs(core)}% for a second straight month.")
    confirmed = cache.timestamp(item["confirmed_at"]).astimezone(NY)
    yesterday = now.astimezone(NY).date() - timedelta(days=1)
    lead = "Yesterday we asked about inflation." if confirmed.date() == yesterday else "We asked about inflation in an earlier brief."
    period = period_for(item["schedule"])
    return f"{lead} In {period:%B}, {core_read(item['result'])}"


def checked_text(item, now):
    row = item["schedule"]
    period = period_for(row)
    due = cache.timestamp(row["at"])
    seen = cache.timestamp(row["fetched_at"])
    if seen > now or not due - PREVIEW <= now <= due + WINDOW:
        raise ValueError("BEA follow-up outside the edition window")
    phase = item["phase"]
    if phase == "preview" and now < due and now - seen <= timedelta(days=1):
        at = due.astimezone(NY)
        question = ("Did underlying inflation ease, and did households spend more after inflation?" if item.get("core_question")
                    else "Did monthly inflation slow, and did households spend more after inflation?")
        return (f"{QUESTION} — {question} "
                f"BEA’s figures are due {at:%A}, {at:%B} {at.day} at {at.strftime('%I:%M %p %Z').lstrip('0')}.")
    if phase == "pending" and now >= due:
        return f"{PENDING} — The scheduled release time has passed. We’re still checking BEA’s monthly inflation and spending figures."
    if phase != "answer":
        raise ValueError("BEA phase conflicts with the edition clock")
    result = item["result"]
    check_result(result, row, now)
    price_before, price = map(Decimal, result["inflation"])
    spend = Decimal(result["real_spending"][1])
    change = "slowed" if price < price_before else "picked up" if price > price_before else "held steady"
    if price == price_before:
        prices = f"monthly PCE inflation {change} at {price}%."
    else:
        prices = f"monthly PCE inflation {change} from {price_before}% to {price}%."
    spending = (f"Households spent {abs(spend)}% {'more' if spend > 0 else 'less'} after inflation."
                if spend else "Inflation-adjusted spending was flat to the nearest tenth of a percent.")
    lead = f"BEA’s {period:%B} figures show "
    if "prior_edition" in item:
        if (not re.fullmatch(r"[a-f0-9]{20}", item["prior_edition"])
                or not cache.timestamp(item["confirmed_at"]) < due):
            raise ValueError("Missing original question delivery")
        lead = f"Our earlier question has an answer. In {period:%B}, "
    if result.get("core_inflation") and "prior_edition" not in item:
        spending += " Excluding food and energy, " + core_read(result)
    if result.get("core_inflation") and "prior_edition" in item:
        lead = f"In {period:%B}, "
    return f"{ANSWER} — {lead}{prices} {spending}"


def source_line(item):
    url = item["result"]["url"] if item["phase"] == "answer" else BEA_URL
    return "BEA inflation and spending — " + url


def validate(item, report, now):
    lines = report.splitlines()
    if not item:
        if any(s.startswith((QUESTION + " —", PENDING + " —", ANSWER + " —")) for s in lines):
            raise ValueError("BEA text has no evidence record")
        return
    from src.reports.daily_voiceover import sections
    text = checked_text(item, now)
    groups = sections(report)
    header = "Policy & Economy" if item["phase"] == "answer" else "What's Ahead"
    notes = report.partition("\nResearch Notes\n")[2].splitlines()
    if lines.count(text) != 1 or text not in groups.get(header, "").splitlines() or notes.count(source_line(item)) != 1:
        raise ValueError("BEA text, section or source changed")


def prepare(now, fetch, editions=None):
    """Resolve the watch before the detailed report fixes its generation clock."""
    try:
        record = cache.load().get("BEA", {})
        fresh = {}
        for row in cache.usable_rows("BEA", record, BEA_URL, now):
            if row["category"] != "pce":
                continue
            try:
                period = period_for(row)
            except ValueError:
                continue
            due = cache.timestamp(row["at"])
            if due - PREVIEW <= now <= due + WINDOW:
                fresh.setdefault(period, {})[due] = row
        delivered = {}
        oldest = (now - WINDOW - PREVIEW).timestamp()
        receipts = {key: stamp for key, stamp in store.checkpoint_receipts(now) if stamp >= oldest}
        if receipts:
            if editions is None:
                editions = store.read_editions(limit=store.MAX_EDITIONS, edition_ids=receipts)
            for edition in editions:
                item = edition.get("pce_watch")
                if not item or edition["id"] not in receipts:
                    continue
                row = item["schedule"]
                built = cache.timestamp(edition["generated_at"])
                confirmed = datetime.fromtimestamp(receipts[edition["id"]], timezone.utc)
                due = cache.timestamp(row["at"])
                if not (built <= confirmed <= now and due - PREVIEW <= now <= due + WINDOW):
                    continue
                validate(item, edition["report_text"], built)
                period = period_for(row)
                states = delivered.setdefault(period, {})
                states.setdefault(item["phase"], (edition["id"], confirmed, row, item.get("core_question") is True))
        for period in sorted(fresh.keys() | delivered.keys(), reverse=True):
            prior = delivered.get(period, {})
            if "answer" in prior or len(fresh.get(period, {})) > 1:
                continue
            previous = prior.get("preview") or prior.get("pending")
            row = next(iter(fresh.get(period, {}).values()), None)
            if row is None:
                if not previous:
                    continue
                row = previous[2]
                if now < cache.timestamp(row["at"]):
                    continue
            due = cache.timestamp(row["at"])
            if now < due:
                if previous and cache.timestamp(previous[2]["at"]) == due:
                    continue
                item = {"phase": "preview", "schedule": row, "core_question": True}
                checked_text(item, now)
                return item
            item = {"phase": "pending", "schedule": row}
            if fetch is not None:
                try:
                    payload = fetch(release_url(period, due))
                    result = capture(payload, row, cache.utc_now())
                    if "preview" in prior and prior["preview"][3] and "core_inflation" not in result:
                        raise ValueError("The delivered underlying inflation question still needs the BEA core row")
                    item.update(phase="answer", result=result)
                    if "preview" in prior:
                        edition_id, confirmed, _, _ = prior["preview"]
                        if confirmed < due:
                            item.update(prior_edition=edition_id, confirmed_at=confirmed.isoformat())
                except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
                    logging.getLogger(__name__).info("BEA figures pending: %s", exc)
            return item
    except (KeyError, ValueError, TypeError, OSError, sqlite3.Error, OverflowError) as exc:
        logging.getLogger(__name__).warning("BEA follow-up unavailable: %s", exc)
    return None


def delivery_summary():
    """Count each delivered question once at its first delivery with verified figures."""
    try:
        receipts = store.checkpoint_receipts(cache.utc_now())
        editions = store.read_editions(limit=store.MAX_EDITIONS, edition_ids=[key for key, _ in receipts])
        by_id = {edition["id"]: edition for edition in editions if edition.get("pce_tracking_version")}
        sent = [by_id[key] for key, _ in receipts if key in by_id]
        window = {edition["id"] for edition in sent[-10:]}
        first_ready = {}
        for edition in sent:
            item = edition.get("pce_watch") or edition.get("pce_answer_omitted") or {}
            if item.get("phase") == "answer" and item.get("prior_edition"):
                key = period_for(item["schedule"])
                first_ready.setdefault(key, (edition["id"], "pce_watch" in edition))
        observed = [included for edition_id, included in first_ready.values() if edition_id in window]
        count = min(len(sent), 10)
        answer = (f"{sum(observed)}/{len(observed)} delivered questions answered in the first brief with verified figures"
                  if observed else "no delivered question with verified figures came due in this window")
        return f"BEA follow-up across the last {count} delivered daily editions: {answer}."
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        return "BEA follow-up delivery history is unavailable."
