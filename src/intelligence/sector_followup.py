"""Close the delivered post-earnings semiconductor question using two aligned ETF returns."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
import re

from src.intelligence.special_alert_sources import NY, timestamp
from src.utils.yahoo_quote import finite_number, return_actions, source_time

SYMBOLS = ("SMH", "SPY")
SOURCE = "Post-earnings closing prices"
LABEL = "Semiconductor close — "
ANSWER = "Our semiconductor check"
QUERY = "range=1mo&interval=1d&events=splits"


def url(symbol):
    return "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol + "?" + QUERY


def question(published_at):
    day = timestamp(published_at).astimezone(NY).date()
    return (f"{LABEL}At the first regular close after Nvidia's {day:%B} {day.day} results, "
            "does the SMH semiconductor ETF gain more, or lose less, than SPY, which tracks the S&P 500?")


def open_question(published_at, when):
    published = timestamp(published_at).astimezone(NY)
    local = when.astimezone(NY)
    if not published <= local or published.hour < 16 or published.weekday() >= 5:
        return False
    # Ask only before the first possible close, including shortened sessions.
    next_weekday = published.date() + timedelta(days=1)
    while next_weekday.weekday() >= 5:
        next_weekday += timedelta(days=1)
    return local.date() < next_weekday or local.date() == next_weekday and local.hour < 13


def delivered(editions, receipts, now):
    by_id = {row["id"]: row for row in editions}
    answered = set()
    candidate = None
    for edition_id, confirmed in reversed(receipts):
        edition = by_id.get(edition_id)
        if not edition or not edition.get("voiceover"):
            continue
        review = edition["analyst_review"]
        prior = review.get("sector_checkpoint")
        if prior and prior.get("quotes"):
            answered.add(prior["published_at"])
        watch = review.get("earnings_watch") or {}
        published = watch.get("published_at")
        if not watch.get("published_outlook") or not published or published in answered:
            continue
        at = timestamp(confirmed)
        built = timestamp(edition["generated_at"])
        if not at or not built or at < built or not open_question(published, at) or at >= now:
            continue
        expected = question(published)
        if expected not in edition["report_text"].splitlines() or not any(
                row["id"] == "watch_semiconductor_close" and row["text"] == expected for row in review["insights"]):
            continue
        if due(published, now):
            candidate = {"edition_id": edition_id, "published_at": published, "confirmed_at": at.isoformat(),
                         "question": expected}
    return candidate


def due(published_at, now):
    local = now.astimezone(NY)
    base = timestamp(published_at).astimezone(NY).date()
    first = base + timedelta(days=1)
    while first.weekday() >= 5:
        first += timedelta(days=1)
    return (first <= local.date() <= first + timedelta(days=4)
            and (local.date() > first or (local.hour, local.minute) >= (16, 15)))


def closing_pair(symbol, packet, base, now):
    raw, observed = packet["chart"], timestamp(packet["observed"])
    meta = raw["meta"]
    if (not observed or observed > now + timedelta(seconds=60) or packet["url"] != url(symbol)
            or raw["request"] != {"range": "1mo", "interval": "1d", "events": "splits"}
            or (meta["symbol"], meta["instrumentType"], meta["currency"], meta["dataGranularity"],
                meta["exchangeTimezoneName"]) != (symbol, "ETF", "USD", "1d", "America/New_York")):
        raise ValueError("ETF identity, observation or daily price basis changed")
    dates = []
    stamps, rows = raw["timestamp"], raw["indicators"]["quote"]
    if len(rows) != 1 or not 2 <= len(stamps) == len(rows[0]["close"]) <= 40:
        raise ValueError("Incomplete daily bars")
    for epoch in stamps:
        at = source_time(epoch)
        if not at or at > observed + timedelta(seconds=60):
            raise ValueError("Invalid daily bar clock")
        dates.append(at.astimezone(NY).date())
    if dates != sorted(set(dates)):
        raise ValueError("Duplicate or unordered daily bars")
    i = dates.index(base)
    if i + 1 >= len(dates):
        raise ValueError("Next closing bar pending")
    day = dates[i + 1]
    last = source_time(meta["regularMarketTime"])
    if (not last or last > observed + timedelta(seconds=60) or day.weekday() >= 5
            or (day-base).days > 4 or day > last.astimezone(NY).date()):
        raise ValueError("Closing session unverified")
    before, close = (finite_number(number) for number in rows[0]["close"][i:i+2])
    if before is None or close is None or min(before, close) <= 0:
        raise ValueError("Missing or invalid close")
    if day == last.astimezone(NY).date():
        end = source_time(meta["currentTradingPeriod"]["regular"]["end"])
        current = finite_number(meta["regularMarketPrice"])
        if not end or current is None or abs(current-close) > max(.01, close*.0001):
            raise ValueError("Latest ETF price does not match the closing bar")
        if end.astimezone(NY).date() == day:
            if observed < end + timedelta(minutes=15) or abs((last-end).total_seconds()) > 60:
                raise ValueError("Latest ETF bar is not a confirmed close")
        elif (end.astimezone(NY).date() <= day or observed.astimezone(NY).date() <= day
              or last.astimezone(NY).strftime("%H:%M") not in {"13:00", "16:00"}):
            raise ValueError("Previous session's closing update is unavailable")
    if day > observed.astimezone(NY).date() or return_actions(raw, {
            "instrument_type": "ETF", "previous_session_date": base.isoformat(), "session_date": day.isoformat()
    }) != "clear":
        raise ValueError("Split or closing date needs review")
    return day, (Decimal(str(close)) / Decimal(str(before)) - 1) * 100


def verdict(checkpoint, now):
    published, confirmed = (timestamp(checkpoint[key]) for key in ("published_at", "confirmed_at"))
    if (not published or not confirmed or not re.fullmatch("[a-f0-9]{20}", checkpoint["edition_id"])
            or checkpoint["question"] != question(checkpoint["published_at"]) or not open_question(published.isoformat(), confirmed)
            or confirmed >= now or not due(published.isoformat(), now)):
        raise ValueError("Invalid delivered semiconductor watch")
    quotes = checkpoint["quotes"]
    if len(json.dumps(quotes, allow_nan=False).encode()) > 32000:
        raise ValueError("ETF evidence exceeds its daily bar limit")
    if quotes == {}:
        return ANSWER + " is waiting for verified closing prices for SMH and SPY."
    if set(quotes) != set(SYMBOLS):
        raise ValueError("Both ETF quotes are required")
    base = published.astimezone(NY).date()
    (day, chip), (other, broad) = [closing_pair(symbol, quotes[symbol], base, now) for symbol in SYMBOLS]
    if day != other:
        raise ValueError("ETF closing dates disagree")
    chip, broad = (value.quantize(Decimal("0.01")) for value in (chip, broad))
    result = "outperformed SPY" if chip > broad else "trailed SPY" if chip < broad else "matched SPY to two decimal places"
    return (f"{ANSWER} at the {day:%B} {day.day} close. SMH returned {chip:+.2f} percent "
            f"and SPY returned {broad:+.2f} percent from the prior close. SMH {result}.")


def capture(prior, now, fetch):
    def read(symbol):
        link = url(symbol)
        response = fetch(link)
        if response.get("status") != "ok" or response.get("url") != link or response.get("final_url", link) != link:
            raise ValueError("Closing chart unavailable")
        body = response.get("body")
        if not isinstance(body, str) or len(body.encode()) > 2_000_000:
            raise ValueError("Invalid closing chart body")
        chart = json.loads(body)["chart"]
        if chart.get("error") or len(chart["result"]) != 1:
            raise ValueError("Ambiguous closing chart")
        raw = chart["result"][0]
        from src.utils.market_quote_source import source_evidence
        proof = source_evidence({**raw, "request": {"range": "1mo", "interval": "1d", "events": "splits"}}, volume=False)
        return {"url": link, "observed": source_time(response["fetched_at_epoch"]).isoformat(), "chart": proof}

    value = {**prior, "quotes": {}}
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            packets = dict(zip(SYMBOLS, pool.map(read, SYMBOLS)))
        verified = {**value, "quotes": packets}
        verdict(verified, now)
        return verified
    except (ValueError, AttributeError, TypeError, KeyError, IndexError, OverflowError, OSError):
        return value


def source_line():
    return "Closing price sources — " + " · ".join(url(symbol) for symbol in SYMBOLS)
