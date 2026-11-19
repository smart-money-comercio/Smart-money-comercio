"""Source-bound defense-company payouts and dated watchlist price context."""

from datetime import date, datetime, time, timedelta
import re

from src.intelligence.special_alert_sources import NY, timestamp
from src.intelligence.watchlist_breadth import market_snapshot


DIVIDEND_TITLE = re.compile(r"Northrop Grumman Board Declares (?:a )?Quarterly (?:Cash )?Dividend\.?", re.I)
MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.? \d{1,2}, 20\d{2}"
DIVIDEND = re.compile(
    r"\b(?:the )?board of directors of Northrop Grumman Corporation(?:\s*\(NYSE:\s*NOC\))? "
    r"(?:has |today )?declared a quarterly (?:cash )?dividend of (?P<amount>\$\d{1,3}(?:\.\d{1,4})?) per share "
    r"on (?:Northrop Grumman|its) common stock, payable (?:on )?(?P<payment>" + MONTH + r"),? "
    r"to (?:shareholders|stockholders) of record (?:as of |at )?(?:the close of business (?:on )?|on )?"
    r"(?P<record>" + MONTH + r")\s*\.(?=\s|$)", re.I)
NO_UPDATE = "No fresh global or defense development qualified for this section."


def calendar_day(value):
    month, rest = value.replace(".", "").split(" ", 1)
    return datetime.strptime(month[:3] + " " + rest, "%b %d, %Y").date()


def dividend_facts(story, text):
    if story.get("publisher_symbol") != "NOC" or not DIVIDEND_TITLE.fullmatch(story["title"]):
        return []
    body = " ".join(text.split())
    matches = list(DIVIDEND.finditer(body))
    if len(matches) != 1 or re.search(r"\b(cancelled|canceled|contingent|conditional|did not|not declared|denied|incorrectly|subject to approval|rescind\w*|suspend\w*|previously declared|proposed dividend)\b", body, re.I):
        return []
    match = matches[0]
    # Other per-share amounts can describe a correction or a different distribution.
    if len(re.findall(r"\$[\d.,]+\s+per share", body, re.I)) != 1:
        return []
    at = timestamp(story.get("published"))
    if not at or float(match["amount"][1:]) == 0:
        return []
    try:
        record, payment = calendar_day(match["record"]), calendar_day(match["payment"])
    except ValueError:
        return []
    if not at.astimezone(NY).date() <= record <= payment:
        return []
    return [{"field": field, "value": match[key], "evidence": match[0]}
            for field, key in (("dividend_per_share", "amount"), ("dividend_record_date", "record"),
                               ("dividend_payment_date", "payment"))]


def dividend_review(evidence):
    values = {row["field"]: row["value"] for row in evidence["facts"]}
    return {"evidence": evidence,
            "facts": (f"Northrop Grumman declared a quarterly dividend of {values['dividend_per_share']} per common share. "
                      f"Shareholders of record on {values['dividend_record_date']} are due to be paid on {values['dividend_payment_date']}."),
            "why": "The dividend sets the next cash payout to shareholders.",
            "watch": "At the next results, compare dividends paid with the cash left after capital spending."}


def price_context(report, now, events):
    """Use only dated extrema from the checked, regular-session watchlist snapshot."""
    from src.intelligence.market_brief import DEFENSE_SYMBOLS
    from src.intelligence.market_event_desk import THRESHOLD

    snapshot = market_snapshot(report)
    statuses = re.findall(r"^Market Session: (Open|Closed)\b.*$", snapshot, re.M)
    sessions = re.findall(r"^Quote session: (\d{4}-\d{2}-\d{2})$", snapshot, re.M)
    clocks = re.findall(r"^Quote timestamps \(UTC\): (.+)$", snapshot, re.M)
    if (len(statuses) != 1 or len(sessions) != 1 or len(clocks) != 1
            or "Scope: watchlist regular-session returns versus dated prior closes." not in snapshot.splitlines()):
        return None
    try:
        day = date.fromisoformat(sessions[0])
    except ValueError:
        return None
    stamps = [timestamp(value) for value in clocks[0].split(" to ")]
    live = statuses == ["Open"]
    local = now.astimezone(NY)
    expected_day = local.date()
    if local.time() < time(9, 30):
        expected_day -= timedelta(days=1)
    while expected_day.weekday() >= 5:
        expected_day -= timedelta(days=1)
    if (day != expected_day or len(stamps) > 2 or any(not at or at.astimezone(NY).date() != day
            or not time(9, 30) <= at.astimezone(NY).time() <= time(16, 1)
            or at > now + timedelta(seconds=60) for at in stamps) or stamps[0] > stamps[-1]
            or live and (day != local.date() or now - stamps[0] > timedelta(minutes=20))):
        return None
    pairs = []
    for label in ("Strongest", "Weakest"):
        rows = re.findall(r"^" + label + r": ([A-Z][A-Z0-9.-]{0,9}) ([+-]?\d{1,4}(?:\.\d{1,2})?)%$", snapshot, re.M)
        if len(rows) != 1:
            return None
        symbol, raw = rows[0]
        pairs.append((symbol, float(raw)))
    if pairs[0][1] < pairs[1][1] or pairs[0][0] == pairs[1][0] and pairs[0][1] != pairs[1][1]:
        return None
    rechecked = {row["symbol"]: row["reported_move"] for row in events if row["status"] == "rechecked"}
    eligible = [(symbol, value) for symbol, value in pairs
                if symbol in DEFENSE_SYMBOLS and 1 <= abs(value) and -100 <= value <= 1000
                and (abs(value) < THRESHOLD or rechecked.get(symbol) == value)]
    if not eligible:
        return None
    symbol, value = max(eligible, key=lambda pair: abs(pair[1]))
    return {"symbol": symbol, "change": value, "session": sessions[0], "open": live}


def global_policy(story):
    """A checked Treasury designation can lead the global section on a quiet defense day."""
    return story.get("kind") == "macro" and story.get("event_evidence", {}).get("schema") == 13


def quiet_copy(quote):
    if not quote:
        return NO_UPDATE
    from src.intelligence.daily_brief_analysis import NAMES
    names = {"ITA": "the iShares U.S. Aerospace & Defense ETF", "GD": "General Dynamics",
             "RTX": "RTX", "HII": "HII", **NAMES}
    day = date.fromisoformat(quote["session"])
    direction = "up" if quote["change"] > 0 else "down"
    clock = "during the regular session" if quote["open"] else "at the close"
    return (f"On {day:%B} {day.day}, {names[quote['symbol']]} was {direction} {abs(quote['change']):.2f} percent {clock}. "
            "No fresh disclosure in this edition explains the move.")
