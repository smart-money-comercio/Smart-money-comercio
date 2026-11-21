"""Dated context for a recent Nvidia result, separate from the fresh-news ledger."""

from datetime import timedelta
from decimal import Decimal
import re

from src.intelligence import nvidia_guidance as nv
from src.intelligence.news_original_sources import article_excerpt
from src.intelligence.special_alert_sources import NY, timestamp
from src.intelligence.weekend_inputs import fresh

SOURCE_SECTION = "This week's earnings comparison"
SOURCE_ID = "recent_nvidia_earnings"
ERRORS = (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError)


def identity(row, now):
    period = nv.results_period(row["title"])
    if not period:
        raise ValueError("Expected Nvidia quarterly results")
    title, url = nv.preceding_release(nv.following_period(period))
    at = timestamp(row["published"])
    day = now.astimezone(NY).date()
    if (row["title"].casefold() != title.casefold() or row["url"] != url or not at or at > now
            or at.astimezone(NY).date() < day - timedelta(days=day.weekday())):
        raise ValueError("Results must belong to this week and the original issuer release")
    return period, at


def metrics(packet, now):
    period, published = identity(packet, now)
    observed = fresh(packet["observed"], now)
    text = packet["text"]
    if observed + timedelta(seconds=60) < published or not isinstance(text, str) or not 80 <= len(text) <= 6000:
        raise ValueError("Invalid original earnings observation")
    story = {"title": packet["title"], "publisher_symbol": "NVDA", "kind": "company"}
    actuals = {r["field"]: r["value"].split(" (")[0] for r in nv.results_facts(story, text)}
    margin = Decimal(actuals["reported_gross_margin"].removesuffix("%"))
    prior = None
    if guide := packet.get("guidance"):
        nv.checked(guide, period, published, now)
        prior = nv.projected_ranges(nv.forward_guidance(guide["outlook"], period)).get("gaap_margin")
    outlook = nv.forward_guidance(text, nv.following_period(period))
    forward = nv.projected_ranges(outlook).get("gaap_margin") if outlook else None
    if not prior and not forward:
        raise ValueError("Comparable original gross-margin guidance unavailable")
    higher_sales = False
    if outlook and "revenue" in outlook:
        lower, _, unit = nv.projected_ranges(outlook)["revenue"]
        reported = re.fullmatch(nv.AMOUNT, actuals["reported_revenue"].replace(",", ""))
        if reported:
            revenue = Decimal(reported[1])
            if reported[2].lower() != unit:
                revenue *= Decimal(1000) if unit == "million" else Decimal("0.001")
            higher_sales = lower > revenue
    return published.astimezone(NY), margin, prior, forward, higher_sales


def capture(rows, now, fetch):
    """Read at most one results release and its preceding issuer guidance."""
    eligible = []
    for row in rows:
        try:
            if (row.get("publisher_symbol") == "NVDA" and row.get("source") == "Nvidia Newsroom"
                    and row.get("kind") == "company" and row.get("official") is True):
                period, at = identity(row, now)
                eligible.append((at, row, period))
        except ERRORS:
            continue
    if not eligible:
        return None
    # On ties prefer a verified original excerpt with the full outlook.
    def rank(item):
        profile = item[1].get("event_evidence") or {}
        body = profile.get("source_text", "")
        return item[0], bool(nv.forward_guidance(body, nv.following_period(item[2]))), len(body)

    at, row, period = max(eligible, key=rank)
    seed = {key: row[key] for key in ("title", "url", "published")}
    packet = None
    try:
        from src.intelligence.story_analysis import checked_evidence
        profile = checked_evidence(row)
        if profile["schema"] == 17 and profile["scope"] == "original release excerpt":
            observed = fresh(profile["observed_at"], now)
            packet = {**seed, "text": profile["source_text"], "observed": observed.isoformat()}
    except ERRORS:
        pass
    if not packet or not nv.forward_guidance(packet["text"], nv.following_period(period)):
        try:
            response = fetch(row["url"])
            if response["status"] == "ok" and response.get("final_url", response["url"]) == row["url"] == response["url"]:
                observed = fresh(response["fetched_at_epoch"], now)
                html = response["body"]
                if not isinstance(html, str) or len(html.encode()) > 2_000_000:
                    raise ValueError("Invalid results page")
                text = article_excerpt(html, row["title"], row["published"], publisher="Nvidia Newsroom", url=row["url"])
                packet = {**seed, "text": text, "observed": observed.isoformat()}
        except ERRORS:
            pass
    if not packet:
        return None
    try:
        guide = nv.capture(row, at, now, fetch)
        if guide and "gaap_margin" in nv.forward_guidance(guide["outlook"], period):
            packet["guidance"] = guide
    except ERRORS:
        pass
    try:
        metrics(packet, now)
        return packet
    except ERRORS:
        return None


def opening(packet, now):
    day, margin, prior, forward, higher_sales = metrics(packet, now)
    text = f"On {day:%A}, Nvidia reported a GAAP gross margin of {nv.decimal_text(margin)} percent"
    if prior:
        low, high, _ = prior
        if margin > high:
            text += f", above its forecast ceiling of {nv.decimal_text(high)} percent"
        elif margin < low:
            text += f", below its forecast floor of {nv.decimal_text(low)} percent"
        else:
            text += f", within its forecast of {nv.format_range(low, high, 'percent')}"
    text += "."
    if forward:
        low, high, unit = forward
        sales = "higher sales and " if higher_sales else ""
        text += f" For next quarter, Nvidia expects {sales}a GAAP gross margin of {nv.format_range(low, high, unit)}"
        if high < margin:
            text += ", meaning less gross profit on each dollar of sales"
        elif low > margin:
            text += ", meaning more gross profit on each dollar of sales"
        text += "."
    return text


def sources(packet):
    refs = [{"url": packet["url"], "publisher": "Nvidia Newsroom", "published_at": packet["published"],
             "verified_at": packet["observed"]}]
    if guide := packet.get("guidance"):
        refs.append({"url": guide["url"], "publisher": "Nvidia Newsroom", "published_at": guide["published_date"],
                     "verified_at": guide["observed"]})
    return refs


def source_line(packet):
    return "Earnings comparison sources — " + " · ".join(ref["url"] for ref in sources(packet))
