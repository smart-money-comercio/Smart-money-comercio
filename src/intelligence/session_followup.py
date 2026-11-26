"""Close an intraday breadth question and put a market reversal in perspective."""

from datetime import date, timedelta
from math import ceil
import re

from src.intelligence import market_priority, research_context, weekend_inputs, weekend_store
from src.intelligence.special_alert_sources import NY, timestamp
from src.utils.yahoo_quote import cached_regular_quote, finite_number, source_time

INDEXES = {"^IXIC": "Nasdaq", "^GSPC": "S&P"}
MARKET_SOURCE = "Benchmark closing history"
WATCH_SOURCE = "Earlier intraday brief"


def close_today(evidence, now):
    return (not evidence["is_open"] and evidence["session"] == now.astimezone(NY).date().isoformat()
            and now.astimezone(NY).weekday() < 5)


def earlier_question(editions, confirmed, session, now):
    """Prefer the most recent delivered question, then the most recent built question."""
    from src.intelligence.daily_brief_analysis import report_evidence

    for edition in sorted(editions, key=lambda row: row["id"] in confirmed, reverse=True):
        at = timestamp(edition.get("generated_at"))
        if not at or at >= now or at.astimezone(NY).date().isoformat() != session:
            continue
        review = edition.get("analyst_review") or {}
        facts = review.get("evidence", {})
        if not facts.get("is_open") or facts.get("session") != session or not facts.get("breadth"):
            continue
        if not edition.get("voiceover") or not any(
            row["name"] == "Editorial Review" and row["status"] == "pass" for row in edition["stages"]
        ):
            continue
        frozen = report_evidence(edition["research_text"])
        if any(facts.get(key) != frozen[key] for key in ("session", "is_open", "moves", "breadth")):
            continue
        question = market_priority.breadth_read(facts)
        for row in review.get("insights", []):
            if (row["id"] == "watch_participation" and row["section"] == "watch"
                    and row["text"].endswith(question) and row["text"] in edition["report_text"].splitlines()):
                return {"edition": edition["id"], "at": edition["generated_at"], "breadth": facts["breadth"],
                        "moves": {key: facts["moves"][key] for key in ("Nasdaq", "S&P", "Russell") if key in facts["moves"]},
                        "question": question}
    return None


def breadth_answer(prior, evidence, now):
    at = timestamp(prior["at"])
    before, after = prior["breadth"], evidence["breadth"]
    if (not at or at >= now or not close_today(evidence, now) or not after
            or at.astimezone(NY).date().isoformat() != evidence["session"]
            or not re.fullmatch(r"[0-9a-f]{20}", prior["edition"])):
        raise ValueError("Closing answer requires an earlier intraday question for this session")
    if any(type(before.get(k)) is not int or before[k] < 0 for k in ("up", "down", "total")) or not (
            0 < before["total"] and before["up"] + before["down"] <= before["total"]):
        raise ValueError("Earlier breadth counts do not reconcile")
    earlier = {"breadth": before, "is_open": True, "moves": prior["moves"]}
    if market_priority.breadth_read(earlier) != prior["question"]:
        raise ValueError("Earlier breadth question changed")
    up, down = before["up"], before["down"]
    moves = [prior["moves"].get(key, 0) for key in ("Nasdaq", "S&P", "Russell")]
    if all(v < 0 for v in moves) and 2 * down <= before["total"]:
        metric = "down"
        lead = ("A majority of the quoted watchlist finished lower." if 2 * after["down"] > after["total"]
                else "Decliners still accounted for half the quoted watchlist or less.")
    elif all(v > 0 for v in moves) and 2 * up <= before["total"]:
        metric = "up"
        lead = ("A majority of the quoted watchlist finished higher." if 2 * after["up"] > after["total"]
                else "Advancers still accounted for half the quoted watchlist or less.")
    elif up == down:
        metric = "up" if after["up"] >= after["down"] else "down"
        lead = ("Advancers took a majority." if 2 * after["up"] > after["total"] else
                "Decliners took a majority." if 2 * after["down"] > after["total"] else
                "Neither side took a majority.")
    else:
        metric = "up" if up > down else "down"
        change = after[metric] * before["total"] - before[metric] * after["total"]
        if metric == "up":
            lead = ("Gains held their breadth into the close." if change == 0 else
                    "Gains spread across more of the quoted watchlist." if change > 0 else
                    "Gains narrowed across the quoted watchlist.")
        else:
            lead = ("Selling eased across the quoted watchlist." if change < 0 else
                    "Selling spread across more of the quoted watchlist." if change > 0 else
                    "The share of the quoted watchlist in decline held steady.")
    label = "higher" if metric == "up" else "lower"
    clock = at.astimezone(NY).strftime("%I:%M %p").lstrip("0").replace("AM", "a.m.").replace("PM", "p.m.")
    return (f"{lead} The {clock} ET brief had {before[metric]} of {before['total']} quoted names {label}. "
            f"At the close, {after[metric]} of {after['total']} finished {label}.")


def prior_weekday(day):
    return day - timedelta(days=3 if day.weekday() == 0 else 1)


def closing_prices(row, symbol, day, reported, now):
    quote = cached_regular_quote(row, now)
    chart = row["quote_evidence"]
    if (quote["symbol"] != symbol or quote["instrument_type"] != "INDEX" or quote["currency"] != "USD"
            or quote["quote_timing"] != "completed_session" or quote["session_date"] != day.isoformat()
            or quote["previous_session_date"] != prior_weekday(day).isoformat()
            or row.get("asof") != quote["asof"] or round(quote["change_percent"], 2) != reported or chart["meta"].get("dataGranularity") != "1d"
            or chart["meta"]["exchangeTimezoneName"] != "America/New_York"):
        raise ValueError("Closing index history differs from this edition")
    end = source_time(chart["meta"]["currentTradingPeriod"]["regular"]["end"])
    asof = timestamp(quote["asof"])
    if not end or not asof or not quote["closing_quote_update"] and abs((asof - end).total_seconds()) > 60:
        raise ValueError("The index quote was not confirmed at the regular close")
    bars = chart["indicators"]["quote"]
    stamps = chart["timestamp"]
    if len(bars) != 1 or not 3 <= len(stamps) == len(bars[0]["close"]) <= 40:
        raise ValueError("Closing index history is incomplete")
    closes = {}
    for epoch, raw in zip(stamps, bars[0]["close"]):
        stamp = source_time(epoch)
        if not stamp or stamp > now or stamp.astimezone(NY).date() in closes:
            raise ValueError("Ambiguous dated index history")
        closes[stamp.astimezone(NY).date()] = finite_number(raw)
    previous = prior_weekday(day)
    before, last, current = (closes.get(key) for key in (prior_weekday(previous), previous, day))
    if not all(v and v > 0 for v in (before, last, current)) or abs(current - quote["price"]) > .011:
        raise ValueError("Exact closing dates and a matching index close are required")
    return before, last, quote["price"]


def pullback_text(packet, evidence, day, now):
    rows = packet["indexes"]
    if set(packet) != {"indexes"} or set(rows) not in ({"^IXIC"}, {"^IXIC", "^DJI"}):
        raise ValueError("Unexpected sources for the Nasdaq pullback")
    loss = -evidence["moves"]["Nasdaq"]
    before, last, current = closing_prices(rows["^IXIC"], "^IXIC", day, -loss, now)
    gain = round(100 * (last / before - 1), 2)
    if gain < 1 or loss <= 0 or current >= last:
        return ""
    if current < before:
        part = "more than erased"
    elif current == before:
        part = "gave back all of"
    elif last - current > (last - before) / 2:
        part = "gave back most of"
    else:
        part = "gave back a slice of"
    upper = ceil(gain)
    prior_gain = f"nearly {upper}%" if upper >= 3 and 0 < upper - gain <= .5 else f"{gain:g}%"
    comparison = ""
    if "^DJI" in rows:
        dow = rows["^DJI"]["move"]
        closing_prices(rows["^DJI"], "^DJI", day, dow, now)
        if dow <= 0:
            raise ValueError("Dow comparison needs a gain at the same close")
        comparison = f", while the Dow gained {dow:.2f}%"
    return (f"The tech-heavy Nasdaq {part} {prior_weekday(day):%A}'s rally. "
            f"After gaining {prior_gain}, it fell {loss:.2f}% on {day:%A}{comparison}.")


def reversal_text(packet, evidence, now, version=3):
    if not close_today(evidence, now):
        raise ValueError("A closing comparison requires today's completed cash session")
    day = date.fromisoformat(evidence["session"])
    if version == 5 and "^GSPC" not in packet["indexes"]:
        return pullback_text(packet, evidence, day, now)
    if version >= 4 and set(packet["indexes"]) != set(INDEXES):
        raise ValueError("Unexpected closing benchmark source")
    prices = [closing_prices(packet["indexes"][sym], sym, day, evidence["moves"][key], now)
              for sym, key in INDEXES.items()]
    if (version == 4 and all(evidence["moves"][key] < 0 for key in INDEXES.values())
            and all(last / before >= 1.01 and current < last for before, last, current in prices)):
        if "week" in packet:
            raise ValueError("Pullback comparison uses only the consecutive index closes")
        before, last, current = prices[0]
        prior = prior_weekday(day)
        part = ("gave back part of" if current > before else "gave back all of" if current == before
                else "more than erased")
        gain = 100 * (last / before - 1)
        loss = abs(evidence["moves"]["Nasdaq"])
        return (f"The Nasdaq {part} {prior:%A}'s rally. After gaining {gain:.2f} percent, "
                f"it fell {loss:.2f} percent at {day:%A}'s close.")
    # A two-index reversal is material enough to lead only after a substantial prior move.
    if not all(last / before <= .99 and current > last for before, last, current in prices):
        return ""
    covered = [current >= before for before, _, current in prices]
    prior = prior_weekday(day)
    if all(covered):
        lead = f"{day:%A}'s rebound erased {prior:%A}'s losses for both the Nasdaq and the S&P 500."
    elif not any(covered):
        lead = f"The Nasdaq and the S&P 500 bounced back on {day:%A}. Both still closed below where they stood before {prior:%A}'s selloff."
    else:
        recovered, other = ("Nasdaq", "S&P 500") if covered[0] else ("S&P 500", "Nasdaq")
        lead = f"The {recovered} recovered {prior:%A}'s loss. The {other} made back only part of it."
    before, last, current = prices[0]
    lead += f" The Nasdaq rose {evidence['moves']['Nasdaq']:.2f} percent after falling {100 * (1 - last / before):.2f} percent."
    if weekly := packet.get("week"):
        at = timestamp(weekly["built"])
        if not at or not at < now:
            raise ValueError("Weekly baseline must precede the closing edition")
        window = weekend_inputs.window(at)
        proof = weekend_inputs.checked_price(weekly["price"], window, at)
        if (proof["symbol"] != "^IXIC" or proof["end_date"] != prior.isoformat()
                or abs(last - proof["end_close"]) > .011):
            raise ValueError("Weekly and daily Nasdaq closes disagree")
        change = 100 * (current / proof["baseline_close"] - 1)
        start = date.fromisoformat(proof["baseline_date"])
        if change <= -.1:
            lead += f" Even after the rebound, it closed {abs(change):.1f} percent below its {start:%B} {start.day} close."
    return lead


def capture(evidence, editions, confirmed, now, version=3):
    if not close_today(evidence, now):
        return None
    result = {}
    if evidence.get("breadth"):
        prior = earlier_question(editions, confirmed, evidence["session"], now)
        if prior:
            result["intraday"] = prior
    rows = research_context.load_market_payload().get("market_moves", [])
    if not isinstance(rows, list):
        return result or None
    if version == 5 and evidence["moves"].get("Nasdaq", 0) < 0:
        by_symbol = {}
        for symbol in ("^IXIC", "^DJI"):
            matches = [row for row in rows if isinstance(row, dict) and row.get("symbol") == symbol]
            if len(matches) == 1:
                by_symbol[symbol] = matches[0]
        if "^IXIC" in by_symbol:
            for indexes in (by_symbol, {"^IXIC": by_symbol["^IXIC"]}):
                market = {"indexes": indexes}
                try:
                    if reversal_text(market, evidence, now, version):
                        result["market"] = market
                        break
                except (ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError):
                    continue
        return result or None
    matching = [row for row in rows if isinstance(row, dict) and row.get("symbol") in INDEXES]
    if len(matching) != len(INDEXES):
        return result or None
    indexes = {row["symbol"]: row for row in matching}
    market = {"indexes": indexes}
    try:
        if not reversal_text(market, evidence, now, version):
            return result or None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError):
        return result or None
    if evidence["moves"]["Nasdaq"] < 0:
        result["market"] = market
        return result
    weekend = weekend_store.latest() or {}
    for row in weekend.get("inputs", {}).get("prices", []):
        if row.get("symbol") == "^IXIC" and row.get("status") == "available":
            try:
                extended = {**market, "week": {"built": weekend["generated_at"], "price": row["proof"]}}
                reversal_text(extended, evidence, now)
                market = extended
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError):
                pass
            break
    result["market"] = market
    return result
