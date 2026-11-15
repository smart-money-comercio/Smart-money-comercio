"""Bind earnings previews and follow-ups to the issuer's original disclosures."""

from datetime import timedelta
import re

from src.intelligence.company_schedule import NY, checked_notice
from src.intelligence.special_alert_sources import timestamp


SOURCE_SECTION = "Issuer earnings watch"
NAME = r"[A-Z][A-Za-z'’.-]+(?: [A-Z][A-Za-z'’.-]+){1,3}"
DEPARTURE = re.compile(r"\bannounced(?: today)? that (" + NAME + r") has resigned as (?:President, )?(?:Chief Executive Officer|CEO)\b")
SUCCESSOR = re.compile(r"^(" + NAME + r"),[^\n]{0,220}? has agreed to serve as [Ii]nterim [Cc]hief [Ee]xecutive [Oo]fficer\b", re.M)
REVENUE = re.compile(r"(\$[\d,.]+\s+(?:billion|million)) \(([^()]+)\)", re.I)
NVIDIA_REVENUE = re.compile(
    r"\bNVIDIA (?:\(NASDAQ:\s*NVDA\) )?(?:today )?reported (?:record )?revenue for the "
    r"((?:first|second|third|fourth) quarter) ended [A-Z][a-z]+ \d{1,2}, 20\d{2},? of "
    r"(\$[\d,.]+\s+(?:billion|million))\b", re.I)
NVIDIA_MARGIN = re.compile(
    r"\bFor the quarter, GAAP (?:gross margin was (?P<gaap>-?\d+(?:\.\d+)?)%|"
    r"and non-GAAP gross margins were (?:both (?P<same>-?\d+(?:\.\d+)?)%|"
    r"(?P<first>-?\d+(?:\.\d+)?)% and -?\d+(?:\.\d+)?%, respectively))\.", re.I)


def preview(notice, now):
    if not notice or not notice.get("event_at"):
        return None
    checked_notice(notice, now)
    at = timestamp(notice["event_at"])
    if not now <= at <= now + timedelta(days=4):
        return None
    value = {"phase": "preview", "notice": notice}
    source = notice["source"]
    published = timestamp(source["published"])
    if (source["excerpt_scope"] == "original release excerpt"
            and now - published <= timedelta(days=7)
            and re.search(r"\bCEO (?:transition|succession)\b", source["title"], re.I)):
        departures = set(DEPARTURE.findall(source["source_excerpt"]))
        successors = set(SUCCESSOR.findall(source["source_excerpt"]))
        if len(departures) == len(successors) == 1 and departures != successors:
            value["transition"] = {"departed": departures.pop(), "interim": successors.pop()}
    return value


def reported_revenue(story, profile):
    if story["publisher_symbol"] == "NVDA":
        values = {(amount, period.lower()) for period, amount in NVIDIA_REVENUE.findall(profile["source_text"])
                  if period.casefold() in story["title"].casefold()}
        return next(iter(values)) if len(values) == 1 else None
    fields = {"reported_revenue", "reported_sales", "reported_net_sales"}
    values = []
    for fact in profile["facts"]:
        if fact["field"] not in fields or not (match := REVENUE.fullmatch(fact["value"])):
            continue
        total = r"\b(?:consolidated|total|companywide|company-wide) (?:revenues?|net sales|sales)\b[^;.,]{0,50}"
        if re.search(total + re.escape(match[1]), fact["evidence"], re.I):
            values.append((match[1], match[2].lower().removesuffix(", reported")))
    return values[0] if len(set(values)) == 1 else None


def followup(previous, previewed_at, story, now):
    from src.intelligence.news_editor import primary_source
    from src.intelligence.story_analysis import checked_evidence

    at = timestamp(previewed_at)
    if at is None or at >= now or not previous or previous.get("phase") != "preview":
        return None
    notice = previous["notice"]
    if preview(notice, at) != previous or story.get("publisher_symbol") != notice["symbol"]:
        return None
    published = timestamp(story["published"])
    event_at = timestamp(notice["event_at"])
    if (not published or not at < published <= now or now - published > timedelta(hours=24)
            or published.astimezone(NY).date() != event_at.astimezone(NY).date()
            or not event_at - timedelta(hours=2) <= published <= event_at + timedelta(hours=6)
            or story.get("kind") != "company" or story.get("decision") != "selected"
            or story.get("source_check") != "pass" or not primary_source(story)):
        return None
    profile = checked_evidence(story)
    observed = timestamp(profile["observed_at"])
    if (profile["event"] != "earnings" or profile["scope"] != "original release excerpt"
            or observed is None or not -60 <= (now - observed).total_seconds() <= 21600
            or (published - observed).total_seconds() > 60):
        return None
    revenue = reported_revenue(story, profile)
    if revenue is None:
        return None
    value = {"phase": "results", "preview": previous, "previewed_at": at.isoformat(),
             "story_id": story["id"], "revenue": revenue[0], "period": revenue[1]}
    if story["publisher_symbol"] == "NVDA":
        # Read the quarter's margins from the same opening as its reported revenue.
        earnings = [line for line in profile["source_text"].splitlines() if (match := NVIDIA_REVENUE.search(line))
                    and (match[2], match[1].lower()) == revenue]
        if len(earnings) == 1 and (margin := NVIDIA_MARGIN.search(earnings[0])):
            figure = next(number for number in margin.groups() if number is not None)
            if -1000 <= float(figure) <= 100:
                value["gaap_margin"] = figure
    return value


def recent_followup(editions, stories, now):
    if not stories:
        return None
    for edition in editions:
        review = edition.get("analyst_review") or {}
        previous = review.get("earnings_watch")
        if not isinstance(previous, dict) or previous.get("phase") != "preview":
            continue
        for story in stories:
            try:
                value = followup(previous, edition["generated_at"], story, now)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if value:
                return value
    return None


def checked(value, now, stories):
    if not isinstance(value, dict) or value.get("phase") not in {"preview", "results"}:
        raise ValueError("Unknown issuer earnings watch")
    if value.get("phase") == "preview":
        expected = preview(value["notice"], now)
    else:
        story = next((row for row in stories if row["id"] == value.get("story_id")), None)
        expected = followup(value["preview"], value["previewed_at"], story, now) if story else None
    if expected != value:
        raise ValueError("Earnings watch does not match the issuer disclosure and edition clock")
    return value


def opening(value, names):
    if value["phase"] == "results":
        symbol = value["preview"]["notice"]["symbol"]
        figures = f"The company reported revenue of {value['revenue']} for the {value['period']}"
        if margin := value.get("gaap_margin"):
            figures += f" and a GAAP gross margin of {margin} percent"
        return f"We were watching {names.get(symbol, symbol)}'s revenue and margins. {figures}."
    notice = value["notice"]
    symbol = notice["symbol"]
    label = names.get(symbol, symbol)
    if transition := value.get("transition"):
        published = timestamp(notice["source"]["published"]).astimezone(NY)
        return (f"{label}'s next earnings report follows a CEO change. On {published:%B} {published.day}, "
                f"the company said {transition['departed']} resigned and {transition['interim']} would serve as interim CEO.")
    return f"{label}'s upcoming earnings give us a check on sales and profitability."


def preview_question(value):
    text = "Compare reported revenue and gross margin with the company's guidance for the quarter."
    if value["notice"]["symbol"] == "NVDA":
        text += " Then check what management says about data center demand and margins."
    return text


def source(value, stories):
    if value["phase"] == "preview":
        return value["notice"]["source"]
    return next(row for row in stories if row["id"] == value["story_id"])


def source_line(value, stories):
    from src.intelligence.news_editor import canonical_url

    return "Original earnings source — " + canonical_url(source(value, stories)["url"])
