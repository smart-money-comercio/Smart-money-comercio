"""Bind earnings previews and follow-ups to the issuer's original disclosures."""

from datetime import date, timedelta
from decimal import Decimal
import re

from src.intelligence.company_schedule import NY, checked_notice
from src.intelligence.special_alert_sources import timestamp


SOURCE_SECTION = "Issuer earnings watch"
COMPARISON_HEADER = "What Changed Since Our Last Brief"
GUIDANCE_SOURCE_ID = "earnings_guidance_NVDA"
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


def followup(previous, previewed_at, story, now, *, guidance=None):
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
    if guidance is not None:
        from src.intelligence import nvidia_guidance

        period = nvidia_guidance.results_period(story["title"]) if story["publisher_symbol"] == "NVDA" else None
        if period is None or period[0] + " quarter" != revenue[1]:
            raise ValueError("Nvidia guidance comparison needs the reported fiscal quarter")
        proof = nvidia_guidance.checked(guidance, period, at, now)
        comparison = nvidia_guidance.comparisons(proof, value, period)
        if not comparison:
            raise ValueError("No reported metric matches the original guidance")
        value.update(guidance=proof, guidance_comparison=comparison, fiscal_year=period[1])
        metric = "gaap_margin" if "gaap_margin" in comparison else "revenue"
        if next_range := nvidia_guidance.next_range(profile["source_text"], period, metric):
            value["next_guidance_range"] = next_range
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


def with_original_guidance(value, story, now, fetch):
    """Read one historical issuer release after a results follow-up qualifies."""
    from src.intelligence import nvidia_guidance

    try:
        proof = nvidia_guidance.capture(story, timestamp(value["previewed_at"]), now, fetch)
        if proof:
            return followup(value["preview"], value["previewed_at"], story, now, guidance=proof)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, OverflowError):
        pass
    return value


def resolve_outlook(story, prior, now):
    """A published forecast can answer a watch even if no earlier preview was archived."""
    from src.intelligence import nvidia_guidance as nv
    from src.intelligence.news_editor import primary_source
    from src.intelligence.story_analysis import checked_evidence

    if (story.get("decision") != "selected" or story.get("source_check") != "pass"
            or story.get("publisher_symbol") != "NVDA" or primary_source(story) != "NVDA"
            or not (period := nv.results_period(story["title"]))):
        return prior
    profile = checked_evidence(story)
    published, observed = timestamp(story["published"]), timestamp(profile.get("observed_at"))
    if (profile["scope"] != "original release excerpt" or profile["event"] != "earnings"
            or not published or not observed or not 0 <= (now-published).total_seconds() <= 86400
            or not -60 <= (now-observed).total_seconds() <= 21600 or published > observed + timedelta(seconds=60)):
        return prior
    outlook = nv.forward_guidance(profile["source_text"], nv.following_period(period))
    if not outlook:
        if prior and prior.get("guidance_comparison"):
            return {**prior, "outlook_checked": True}
        return prior
    try:
        actuals = nv.results_facts(story, profile["source_text"])
    except ValueError:
        return prior
    facts = {fact["field"]: fact["value"].partition(" (")[0] for fact in actuals}
    base = prior or {"phase": "results", "story_id": story["id"], "period": period[0] + " quarter",
                     "fiscal_year": period[1], "revenue": facts["reported_revenue"]}
    value = {**base, "fiscal_year": period[1], "published_outlook": outlook, "published_at": published.isoformat()}
    if "reported_gross_margin" in facts:
        value["gaap_margin"] = facts["reported_gross_margin"].removesuffix("%")
    from src.intelligence.sector_followup import open_question
    if open_question(value["published_at"], now):
        value["sector_watch"] = True
    return value


def has_answer(value):
    return bool(value and (value.get("guidance_comparison") or value.get("published_outlook")))


def outlook_text(value):
    outlook = value["published_outlook"]
    parts = []
    if rev := outlook.get("revenue"):
        parts.append(f"revenue of ${rev['center']} {rev['unit']}, plus or minus {rev['tolerance']} percent")
    if margin := outlook.get("gaap_margin"):
        parts.append(f"a GAAP gross margin of {margin['low']} to {margin['high']} percent")
    timing = f"the {outlook['quarter']} quarter of fiscal {outlook['year']}"
    if outlook["additional_week"]:
        timing += ", which includes an extra week"
    return f"For {timing}, management expects " + " and ".join(parts) + "."


def outlook_opening(value):
    from src.intelligence.nvidia_guidance import AMOUNT, projected_ranges
    bounds = projected_ranges(value["published_outlook"])
    revenue = re.fullmatch(AMOUNT, value["revenue"].replace(",", ""))
    if revenue and "revenue" in bounds and "gaap_margin" in bounds and "gaap_margin" in value:
        low, high, unit = bounds["revenue"]
        actual = Decimal(revenue[1])
        if revenue[2].lower() != unit:
            actual *= Decimal(1000) if unit == "million" else Decimal("0.001")
        margin_low, margin_high, _ = bounds["gaap_margin"]
        margin = Decimal(value["gaap_margin"])
        if low > actual and margin_high < margin:
            return "Nvidia expects higher sales next quarter and a smaller gross profit on each dollar of revenue."
        if low > actual and margin_low > margin:
            return "Nvidia expects both sales and gross margin to rise next quarter."
    return "Nvidia has set new targets for " + ("sales and gross margin." if len(bounds) == 2 else
            "sales." if "revenue" in bounds else "gross margin.")


def checked(value, now, stories):
    if not isinstance(value, dict) or value.get("phase") not in {"preview", "results"}:
        raise ValueError("Unknown issuer earnings watch")
    if value.get("phase") == "preview":
        expected = preview(value["notice"], now)
    else:
        story = next((row for row in stories if row["id"] == value.get("story_id")), None)
        expected = None
        if story and "preview" in value:
            expected = followup(value["preview"], value["previewed_at"], story, now, guidance=value.get("guidance"))
        if story and ("published_outlook" in value or value.get("outlook_checked")):
            expected = resolve_outlook(story, expected, now)
    if expected != value:
        raise ValueError("Earnings watch does not match the issuer disclosure and edition clock")
    return value


def opening(value, names):
    if value.get("published_outlook"):
        return outlook_opening(value)
    if value["phase"] == "results":
        symbol = value["preview"]["notice"]["symbol"]
        if comparison := value.get("guidance_comparison"):
            revenue = comparison.get("revenue", {}).get("position")
            margin = comparison.get("gaap_margin", {}).get("position")
            if revenue == "above" and margin == "below":
                return "Nvidia's results put the cost of delivering its sales in focus."
            if revenue == "above" and margin:
                return "Nvidia's results support the case that stronger sales can come with gross margins at or above management's target."
            if revenue == "below":
                return "Nvidia's revenue shortfall makes its next sales outlook more important."
            if margin == "below":
                return "Nvidia's gross margin miss puts the costs of delivering its sales in focus."
            return "Nvidia's results give us a benchmark for judging management's next outlook."
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


def comparison_text(value):
    comparison = value.get("guidance_comparison", {})
    if not comparison:
        text = f"Nvidia reported {value['revenue']} in revenue for the {value['period']} of fiscal {value['fiscal_year']}."
        if "gaap_margin" in value:
            text += f" GAAP gross margin was {value['gaap_margin']} percent."
        return text + " " + outlook_text(value)
    published = date.fromisoformat(value["guidance"]["published_date"])
    sentences = []
    if revenue := comparison.get("revenue"):
        sentences.append(
            f"Nvidia reported {revenue['actual']} in revenue for the {value['period']} of fiscal {value['fiscal_year']}. "
            f"That was {revenue['position']} its original {revenue['range']} range."
        )
    if margin := comparison.get("gaap_margin"):
        subject = ("GAAP gross margin" if revenue else
                   f"Nvidia's GAAP gross margin for the {value['period']} of fiscal {value['fiscal_year']}")
        sentences.append(
            f"{subject} was {margin['actual']}, {margin['position']} the original "
            f"{margin['range']} range."
        )
    sentences.append(f"Nvidia issued that guidance on {published:%B} {published.day}.")
    if value.get("published_outlook"):
        sentences.append(outlook_text(value))
    return " ".join(sentences)


def next_guidance_check(value):
    if outlook := value.get("published_outlook"):
        if band := outlook.get("gaap_margin"):
            return f"When Nvidia reports its {outlook['quarter']} quarter, compare actual GAAP gross margin with the {band['low']} to {band['high']} percent it now expects."
        return f"When Nvidia reports its {outlook['quarter']} quarter, compare actual sales with management's new revenue range."
    if bounds := value.get("next_guidance_range"):
        metric = "GAAP gross margin" if "gaap_margin" in value["guidance_comparison"] else "revenue"
        return f"Management's next-quarter {metric} guidance is {bounds}. Use it as the benchmark when the company next reports or updates its outlook."
    if value.get("outlook_checked"):
        if margin := value.get("gaap_margin"):
            return f"At the next quarterly release, compare actual GAAP gross margin with the {margin} percent just reported."
        return f"At the next quarterly release, compare reported revenue with this quarter's {value['revenue']}."
    if "gaap_margin" in value["guidance_comparison"]:
        return (
            f"Check the next quarter's GAAP gross-margin guidance against the {value['gaap_margin']} percent just reported. "
            "That will show whether management expects to keep the same margin as sales change."
        )
    return (
        f"Check the next quarter's revenue guidance against the {value['revenue']} just reported. "
        "That will show how much follow-through management expects."
    )


def guidance_source_line(value):
    return "Original guidance source — " + value["guidance"]["url"]
