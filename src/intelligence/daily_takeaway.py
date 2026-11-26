"""The lead fact and its immediate context for a current Daily Brief."""

from datetime import date


VERSION = 5
INDEXES = (("Nasdaq", "the Nasdaq Composite"), ("S&P", "the S&P 500"), ("Russell", "the Russell 2000"))


# The calendar verifies timing; the question describes what that release measures.
CALENDAR_TESTS = {
    ("BEA", "pce"): ("inflation and personal spending figures", "whether prices are easing while households keep spending"),
    ("BEA", "gdp"): ("GDP report", "whether consumer spending or business investment is driving growth"),
    ("BLS", "cpi"): ("consumer price report", "whether price increases are concentrated or widespread"),
    ("BLS", "jobs"): ("jobs report", "whether hiring and wage growth are slowing together"),
    ("DOL", "claims"): ("jobless claims release", "whether more workers are filing for unemployment benefits"),
}
CALENDAR_SECTION = "Upcoming publisher release"
CALENDAR_ID = "takeaway_calendar"


def calendar_text(row, now, version=3):
    from datetime import timedelta
    from src.intelligence import calendar_context as calendar, calendar_sources as publishers
    at = calendar.checked_time(row["event_at"]).astimezone(publishers.NY)
    observed = calendar.checked_time(row["timing_checked_at"])
    publisher = row["publisher"]
    family = publishers.category(row["eventName"])
    if (row["time_status"] != "verified" or row.get("timing_cached") or (publisher, family) not in CALENDAR_TESTS
            or row["timing_url"] != publishers.SOURCE_URLS[publisher] or at.date().isoformat() != row["source_date"]
            or version >= 4 and observed > now
            or not now < at <= now + timedelta(days=7) or not -60 <= (now - observed).total_seconds() <= 86400):
        raise ValueError("Upcoming release needs a current verified publisher schedule")
    if version >= 5 and (publisher, family) == ("BEA", "pce"):
        gap = (at.date() - now.astimezone(publishers.NY).date()).days
        when = "Today" if gap == 0 else "Tomorrow" if gap == 1 else at.strftime("%A")
        clock = at.strftime("%I:%M %p").lstrip("0").replace("AM", "a.m.").replace("PM", "p.m.")
        return (f"{when} at {clock} ET, attention shifts to inflation. "
                "We’ll be watching whether underlying prices rose more slowly than they did a month earlier.")
    if version >= 4 and (publisher, family) == ("BEA", "pce"):
        clock = at.strftime("%I:%M %p %Z").lstrip("0")
        return f"On {at:%A} at {clock}, we’ll see whether prices rose more slowly once food and energy are excluded."
    label, question = CALENDAR_TESTS[publisher, family]
    return f"{at:%A}'s {label} will help show {question}."


def next_calendar(rows, now, version=3):
    from src.intelligence.calendar_context import checked_time
    eligible = []
    for row in rows:
        try:
            calendar_text(row, now, version)
            eligible.append(row)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
    from src.intelligence.calendar_sources import category
    return min(eligible, key=lambda row: (checked_time(row["event_at"]),
               version >= 4 and category(row["eventName"]) != "pce", row["publisher"], row["eventName"]), default=None)


def _cash_lead(evidence):
    if not evidence["session"]:
        return ""
    at = date.fromisoformat(evidence["session"]).strftime("%A")
    when = f"in {at}'s session" if evidence["is_open"] else f"at {at}'s close"
    values = [(name, round(evidence["moves"][key], 2)) for key, name in INDEXES if key in evidence["moves"]]
    if not values:
        return ""
    moves = [f"{name} {'down' if change < 0 else 'up'} {abs(change):.2f} percent" if change else f"{name} unchanged"
             for name, change in values[:2]]
    if len(values) == 1:
        return f"The available index reading {when} showed {moves[0]}."
    changes = [change for _, change in values]
    lead = ("Stocks fell" if all(change < 0 for change in changes) else
            "Stocks rose" if all(change > 0 for change in changes) else
            "The major indexes were flat" if not any(changes) else "The major indexes were mixed")
    return f"{lead} {when}, with {' and '.join(moves)}."


def _futures_lead(value, version):
    from src.intelligence import early_futures

    nasdaq, broad = (round(row["change"], 2) for row in value["quotes"])
    lead = "Early losses were steeper in tech-heavy futures. " if nasdaq < broad < 0 else ""
    if version in (3, 4, 5):
        lead = ""
        if broad < 0 and round(broad - nasdaq, 2) >= .15:
            lead = "Tech-heavy futures led the early decline. "
        elif broad > 0 and round(nasdaq - broad, 2) >= .15:
            lead = "Tech-heavy futures led the early gains. "
    if version in (4, 5):
        then = [row["prior_bar_change"] for row in value["quotes"]]
        changes = [row["change"] for row in value["quotes"]]
        # Speak only when both contracts' moves since the prior cash close
        # changed materially in the same direction over the same five minutes.
        if all(round(current, 2) < 0 and prior < 0 and round(prior - current, 6) >= .15 for current, prior in zip(changes, then)):
            return early_futures.opening(value) + " Both contracts slipped further over the preceding five minutes."
        if all(round(current, 2) < 0 and round(current - prior, 6) >= .15 for current, prior in zip(changes, then)):
            return early_futures.opening(value) + " Both contracts trimmed their losses over the preceding five minutes."
    return lead + early_futures.opening(value)


def _earnings_line(watch):
    from src.intelligence import earnings_watch
    from src.intelligence.daily_brief_analysis import NAMES

    if watch["phase"] == "preview":
        notice = watch["notice"]
        label = NAMES.get(notice["symbol"], notice["symbol"])
        day = date.fromisoformat(notice["event_date"]).strftime("%A")
        return f"{label}'s {day} earnings are the next test of how gross margins held up against management's guidance."
    if earnings_watch.has_answer(watch):
        return earnings_watch.opening(watch, NAMES)
    symbol = watch["preview"]["notice"]["symbol"]
    label = NAMES.get(symbol, symbol)
    margin = f" and a GAAP gross margin of {watch['gaap_margin']} percent" if watch.get("gaap_margin") else ""
    return f"{label} reported revenue of {watch['revenue']} for the {watch['period']}{margin}."


def market_read(evidence):
    """Explain the breadth or divergence visible in the dated indexes."""
    if not evidence.get("session"):
        return ""
    moves = evidence["moves"]
    if not all(key in moves for key, _ in INDEXES):
        return ""
    nasdaq, broad, small = (moves[key] for key, _ in INDEXES)
    day = date.fromisoformat(evidence["session"]).strftime("%A")
    during = evidence["is_open"]
    when = f"during {day}'s session" if during else f"at {day}'s close"
    if nasdaq < min(broad, small) and max(broad, small) < 0 and evidence.get("earnings_takeaway_text"):
        if during:
            return f"The Nasdaq Composite is leading {day}'s decline, down {abs(nasdaq):.2f} percent as large companies and small caps also lose ground."
        return f"The Nasdaq Composite led {day}'s selloff, falling {abs(nasdaq):.2f} percent as large companies and small caps also lost ground."
    if evidence.get("takeaway_version") in (3, 4, 5):
        if nasdaq > broad > 0 and small > 0:
            return (f"Small caps joined the rally. The Nasdaq Composite "
                    f"{'is up' if during else 'rose'} {nasdaq:.2f} percent {when}, "
                    f"and the Russell 2000 {'is up' if during else 'gained'} {small:.2f} percent.")
        if nasdaq < broad < 0 and small < 0:
            return (f"The selling reached beyond the Nasdaq {when}. "
                    f"The Nasdaq Composite {'is down' if during else 'fell'} {abs(nasdaq):.2f} percent, "
                    f"and the Russell 2000 {'is down' if during else 'lost'} {abs(small):.2f} percent.")
    if nasdaq < broad < 0 and small < 0:
        return (f"Large companies and small caps both lost ground {when}. "
                f"The Nasdaq Composite {'is down' if during else 'fell'} {abs(nasdaq):.2f} percent, "
                f"compared with {abs(broad):.2f} percent for the S&P 500.")
    if nasdaq > broad > 0 and small > 0:
        return (f"Gains reached both large companies and small caps {when}. "
                f"The Nasdaq Composite {'is up' if during else 'rose'} {nasdaq:.2f} percent, "
                f"compared with {broad:.2f} percent for the S&P 500.")
    if all(value < 0 for value in (nasdaq, broad, small)) or all(value > 0 for value in (nasdaq, broad, small)):
        verb = "lost" if broad < 0 else "gained"
        return (f"Large companies and small caps both {verb} ground {when}. "
                f"The S&P 500 {verb} {abs(broad):.2f} percent and the Russell 2000 {verb} {abs(small):.2f} percent.")
    if nasdaq * small < 0:
        return (f"The Nasdaq Composite and small caps moved in opposite directions {when}. "
                f"The Nasdaq {'gained' if nasdaq > 0 else 'lost'} {abs(nasdaq):.2f} percent while "
                f"the Russell 2000 {'gained' if small > 0 else 'lost'} {abs(small):.2f} percent.")
    return ""


def compose(evidence):
    """Return the copy and exactly the evidence roles used in it."""
    from src.intelligence.evidence_opening import opening_source
    from src.intelligence.market_priority import selloff

    futures = evidence.get("premarket_futures")
    watch = evidence.get("earnings_watch")
    reversal = evidence.get("reversal")
    if evidence.get("core_pce_lead"):
        market = _futures_lead(futures, 4) if futures else evidence.get("core_pce_market_text", "")
        return {"text": " ".join(filter(None, (evidence["core_pce_lead"], market))),
                "market": bool(market), "earnings": False, "recent_result": False, "calendar": False,
                "point": None, "story_ids": []}
    if reversal and not futures:
        calendar = evidence.get("takeaway_calendar_text") if evidence.get("takeaway_version") in (4, 5) else None
        return {"text": " ".join(filter(None, (reversal, calendar))), "market": True, "earnings": False, "recent_result": False,
                "calendar": bool(calendar), "point": None, "story_ids": []}
    market_first = bool(futures) or selloff(evidence)
    context = evidence.get("earnings_takeaway_text")
    point = opening_source(evidence) if not (market_first or watch or context) else None
    use_context = bool(context and not point and (not watch or watch["phase"] == "results"))
    modern = evidence.get("takeaway_version") in (2, 3, 4, 5)
    market = ""
    if futures:
        market = _futures_lead(futures, evidence.get("takeaway_version"))
    elif not point and (not watch or watch["phase"] == "preview" or market_first):
        market = (market_read(evidence) if modern else "") or _cash_lead(evidence)

    sentences = [market] if market else []
    story_ids = []
    if point:
        sentences.append(point["text"])
        story_ids.extend(point["story_ids"])
    if use_context:
        sentences.append(context)
    elif watch:
        sentences.append(_earnings_line(watch))
    if not use_context and not point and (not watch or watch["phase"] == "preview"):
        from src.intelligence.ipo_monitor import checked

        ipo = next((story for story in evidence.get("stories", [])
                    if story.get("ipo", {}).get("stage") in {"terms", "priced"}), None)
        if ipo:
            name = checked(ipo)["name"]
            text = (f"{name}'s IPO price offers a read on what investors will pay for its growth." if ipo["ipo"]["stage"] == "priced" else
                    f"{name}'s proposed IPO range sets a benchmark for its eventual pricing.")
            sentences.append(text)
            story_ids.append(ipo["id"])
    use_calendar = bool(modern and evidence.get("takeaway_calendar_text") and not (point or watch or use_context or story_ids))
    if use_calendar:
        sentences.append(evidence["takeaway_calendar_text"])
    elif modern and sentences == [market] and market and not futures and selloff(evidence):
        if evidence["moves"].get("VIX", 0) > 0:
            sentences.append("The VIX also rose, signaling higher expected volatility in the S&P 500 over the next month.")
    if not sentences:
        sentences.append("The available evidence gives a limited read on market direction.")
    return {"text": " ".join(sentences), "market": bool(market), "earnings": bool(watch) and not use_context, "recent_result": use_context, "calendar": use_calendar, "point": point, "story_ids": story_ids}
