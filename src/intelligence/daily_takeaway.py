"""The lead fact and its immediate context for a current Daily Brief."""

from datetime import date


VERSION = 1
INDEXES = (("Nasdaq", "the Nasdaq Composite"), ("S&P", "the S&P 500"), ("Russell", "the Russell 2000"))


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


def _futures_lead(value):
    from src.intelligence import early_futures

    nasdaq, broad = (round(row["change"], 2) for row in value["quotes"])
    lead = "Early losses were steeper in tech-heavy futures. " if nasdaq < broad < 0 else ""
    return lead + early_futures.opening(value)


def _earnings_line(watch):
    from src.intelligence import earnings_watch
    from src.intelligence.daily_brief_analysis import NAMES

    if watch["phase"] == "preview":
        notice = watch["notice"]
        label = NAMES.get(notice["symbol"], notice["symbol"])
        day = date.fromisoformat(notice["event_date"]).strftime("%A")
        return f"{label}'s {day} earnings are the next test of how gross margins held up against management's guidance."
    if watch.get("guidance_comparison"):
        return earnings_watch.opening(watch, NAMES)
    symbol = watch["preview"]["notice"]["symbol"]
    label = NAMES.get(symbol, symbol)
    margin = f" and a GAAP gross margin of {watch['gaap_margin']} percent" if watch.get("gaap_margin") else ""
    return f"{label} reported revenue of {watch['revenue']} for the {watch['period']}{margin}."


def compose(evidence):
    """Return the copy and exactly the evidence roles used in it."""
    from src.intelligence.evidence_opening import opening_source
    from src.intelligence.market_priority import selloff

    futures = evidence.get("premarket_futures")
    watch = evidence.get("earnings_watch")
    market_first = bool(futures) or selloff(evidence)
    point = opening_source(evidence) if not market_first and not watch else None
    market = ""
    if futures:
        market = _futures_lead(futures)
    elif not point and (not watch or watch["phase"] == "preview" or market_first):
        market = _cash_lead(evidence)

    sentences = [market] if market else []
    story_ids = []
    if point:
        sentences.append(point["text"])
        story_ids.extend(point["story_ids"])
    if watch:
        sentences.append(_earnings_line(watch))
    if not point and (not watch or watch["phase"] == "preview"):
        from src.intelligence.ipo_monitor import checked

        ipo = next((story for story in evidence.get("stories", [])
                    if story.get("ipo", {}).get("stage") in {"terms", "priced"}), None)
        if ipo:
            name = checked(ipo)["name"]
            text = (f"{name}'s IPO price offers a read on what investors will pay for its growth." if ipo["ipo"]["stage"] == "priced" else
                    f"{name}'s proposed IPO range sets a benchmark for its eventual pricing.")
            sentences.append(text)
            story_ids.append(ipo["id"])
    if not sentences:
        sentences.append("The available evidence gives a limited read on market direction.")
    return {"text": " ".join(sentences), "market": bool(market), "earnings": bool(watch), "point": point, "story_ids": story_ids}
