"""Connect a delivered Michigan survey question with its official final reading."""

from calendar import month_name
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import unescape
import re

from src.intelligence import calendar_source_cache as cache
from src.intelligence.calendar_sources import MICHIGAN_URL, NY
from src.intelligence.stockanalysis_source import TableParser

QUESTION = "Consumer confidence watch"
ANSWER = "Our consumer confidence check"
SOURCE = "University of Michigan survey — " + MICHIGAN_URL
SOURCE_ID = "michigan_survey"
HEADING = re.compile(r"(Preliminary|Final) Results for ([A-Za-z]+) (20\d{2})", re.I)
INDEX = "Index of Consumer Sentiment"
MAX_AGE = timedelta(hours=24)


def period_of(heading):
    match = HEADING.fullmatch(heading)
    months = [name.lower() for name in month_name]
    if not match or match[2].lower() not in months[1:]:
        raise ValueError("Unrecognized Michigan survey heading")
    return date(int(match[3]), months.index(match[2].lower()), 1)


def checked_table(table):
    period = period_of(table["heading"])
    prior = period - timedelta(days=1)
    year_ago = period.replace(year=period.year - 1)
    expected = [day.strftime("%b %Y").lower() for day in (period, prior, year_ago)]
    if (table["url"] != MICHIGAN_URL or table["columns"] != expected
            or table["row"] != INDEX or not isinstance(table["levels"], list) or len(table["levels"]) != 2):
        raise ValueError("Unmatched Michigan survey columns")
    components = table.get("components", {})
    if not isinstance(components, dict) or (components and set(components) != {"current", "expectations"}):
        raise ValueError("Incomplete Michigan survey components")
    pairs = [table["levels"], *components.values()]
    if any(not isinstance(pair, list) or len(pair) != 2 for pair in pairs):
        raise ValueError("Incomplete Michigan survey levels")
    for level in (number for pair in pairs for number in pair):
        if not re.fullmatch(r"\d{1,3}(?:\.\d)?", level) or not 0 < float(level) <= 200:
            raise ValueError("Invalid Michigan sentiment index")
    cache.timestamp(table["observed"])
    return period


def capture(html, now):
    """Capture the dated headline index and optional components from the same table."""
    clean = re.sub(r"<!--.*?-->|<(script|style)\b[^>]*>.*?</\1\s*>", " ", html, flags=re.I | re.S)
    headings = list(re.finditer(r"<(h[1-6])\b[^>]*>(.*?)</\1\s*>", clean, flags=re.I | re.S))
    tables = []
    for i, match in enumerate(headings):
        title = " ".join(unescape(re.sub(r"<[^>]*>", " ", match[2])).split())
        if not HEADING.fullmatch(title):
            continue
        parser = TableParser()
        parser.feed(clean[match.end():headings[i+1].start() if i+1 < len(headings) else len(clean)])
        for rows in parser.tables:
            for at, row in enumerate(rows):
                if len(row) < 4 or row[0].casefold() != INDEX.casefold() or at == 0:
                    continue
                # The publisher shows current month, previous month and year-ago.
                # Some templates split month and year over two header rows.
                headers = rows[at-1]
                # A row-spanning blank corner can leave the year row one cell shorter.
                offset = 0 if len(headers) == len(row) - 1 and re.fullmatch(r"20\d{2}", headers[0]) else 1
                columns = headers[offset:offset+3]
                if at >= 2 and len(columns) == 3 and all(re.fullmatch(r"20\d{2}", s) for s in columns):
                    columns = [m + " " + y for m, y in zip(rows[at-2][1:4], columns)]
                table = {"heading": title, "columns": [s.lower() for s in columns], "row": INDEX,
                         "levels": row[1:3], "url": MICHIGAN_URL, "observed": now.isoformat()}
                components = {}
                for key, label in (("current", "Current Economic Conditions"), ("expectations", "Index of Consumer Expectations")):
                    matches = [r[1:3] for r in rows[at+1:] if len(r) >= 4 and r[0].casefold() == label.casefold()]
                    if len(matches) == 1 and all(re.fullmatch(r"\d{1,3}(?:\.\d)?", x) and 0 < float(x) <= 200 for x in matches[0]):
                        components[key] = matches[0]
                if len(components) == 2:
                    table["components"] = components
                try:
                    checked_table(table)
                except (ValueError, TypeError):
                    return None
                tables.append(table)
    return tables[0] if len(tables) == 1 else None


def preview_text(item):
    month = period_of(item["preliminary"]["heading"]).strftime("%B")
    at = cache.timestamp(item["due"]).astimezone(NY)
    early, previous = item["preliminary"]["levels"]
    direction = ("improvement" if float(early) > float(previous) else
                 "decline" if float(early) < float(previous) else "steady reading")
    clock = at.strftime("%A at %I:%M %p %Z").replace(" 0", " ")
    return (f"{QUESTION} — Michigan releases its final {month} survey {clock}. "
            f"Will the early {direction} hold? The preliminary index was {early}, against {previous} the month before.")


def answer_text(item):
    final = item["final"]
    month = period_of(final["heading"]).strftime("%B")
    value, previous = final["levels"]
    early = item["preliminary"]["levels"][0]
    final_level, early_level, prior_level = map(float, (value, early, previous))
    if early_level == prior_level:
        message = ("Sentiment held steady" if final_level == prior_level else "Sentiment improved" if final_level > prior_level else "Sentiment weakened")
    elif final_level == prior_level:
        message = "The early move faded"
    elif (final_level > prior_level) != (early_level > prior_level):
        message = "The early move reversed"
    else:
        message = "The improvement held" if final_level > prior_level else "The decline held"
    copy = (f"{ANSWER} — {message}. Michigan’s final {month} index came in at {value}, "
            f"compared with the preliminary {early} and {previous} the month before.")
    if components := final.get("components"):
        current, expectations = (Decimal(components[k][0]) - Decimal(components[k][1]) for k in ("current", "expectations"))
        if expectations > current > 0:
            copy += " Households’ expectations improved more than their assessment of current conditions."
        elif expectations < current < 0:
            copy += " Households’ expectations fell more sharply than their assessment of current conditions."
    return copy + f" Watch {month} retail sales for a check on actual spending."


def last_answer_day(due):
    day = due.astimezone(NY).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def checked_text(item, now):
    pre = item["preliminary"]
    period = checked_table(pre)
    due = cache.timestamp(item["due"])
    seen = cache.timestamp(pre["observed"])
    if (not pre["heading"].lower().startswith("preliminary ") or period != due.astimezone(NY).date().replace(day=1)
            or seen >= due or seen > now):
        raise ValueError("Michigan preview period or clock changed")
    if "final" not in item:
        if not now < due <= now + timedelta(hours=48) or now - seen > MAX_AGE:
            raise ValueError("Michigan preview outside the release window")
        return preview_text(item)
    final = item["final"]
    confirmed = cache.timestamp(item["confirmed_at"])
    observed = cache.timestamp(final["observed"])
    if (checked_table(final) != period or not final["heading"].lower().startswith("final ")
            or pre["levels"][1] != final["levels"][1]
            or not re.fullmatch(r"[0-9a-f]{20}", item["prior_edition"])
            or not seen <= confirmed < due <= observed <= now or now - observed > MAX_AGE
            or now.astimezone(NY).date() > last_answer_day(due)):
        raise ValueError("Michigan final does not match the delivered question")
    return answer_text(item)


def select(record, editions, receipts, now):
    """Only confirmed Telegram deliveries open or retire a reader question."""
    try:
        table = record["survey"]
        period = checked_table(table)
        if not timedelta(0) <= now - cache.timestamp(table["observed"]) <= MAX_AGE:
            return None
        if table["heading"].lower().startswith("preliminary "):
            rows = cache.usable_rows("Michigan", record, MICHIGAN_URL, now)
            due = [row["at"] for row in rows if row["name"] == "Michigan Consumer Sentiment (Final)"
                   and cache.timestamp(row["fetched_at"]) == cache.timestamp(table["observed"])]
            if len(due) != 1:
                return None
            item = {"preliminary": table, "due": due[0]}
        else:
            by_id = {row["id"]: row for row in editions}
            item = None
            for edition_id, confirmed in reversed(receipts):
                edition = by_id.get(edition_id) or {}
                prior = edition.get("sentiment_watch")
                if not prior or period_of(prior["preliminary"]["heading"]) != period:
                    continue
                built = cache.timestamp(edition["generated_at"])
                delivered = datetime.fromtimestamp(confirmed, timezone.utc)
                if not built <= delivered <= now:
                    continue
                line = checked_text(prior, built)
                if line not in edition["report_text"].splitlines():
                    continue
                if "final" in prior:
                    return None
                if item is None and delivered < cache.timestamp(prior["due"]):
                    item = {**prior, "prior_edition": edition_id, "confirmed_at": delivered.isoformat(), "final": table}
            if item is None:
                return None
        checked_text(item, now)
        return item
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None


def validate_report(item, report, now):
    if not item:
        if any(line.startswith((QUESTION + " — ", ANSWER + " — ")) for line in report.splitlines()):
            raise ValueError("Michigan follow-up lost its source record")
        return
    text = checked_text(item, now)
    header = "Policy & Economy" if "final" in item else "What's Ahead"
    from src.reports.daily_voiceover import sections
    groups = sections(report)
    if (text not in groups.get(header, "").splitlines() or report.splitlines().count(text) != 1
            or SOURCE not in report.partition("\nResearch Notes\n")[2].splitlines()):
        raise ValueError("Michigan survey copy or source differs from its edition")
