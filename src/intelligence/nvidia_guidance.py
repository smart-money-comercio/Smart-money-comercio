"""Compare a reported fiscal quarter with Nvidia's original outlook for it."""

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import re

from src.intelligence.news_original_sources import ArticleBody
from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
from src.intelligence.special_alert_sources import timestamp


QUARTERS = ("first", "second", "third", "fourth")
RESULTS_TITLE = re.compile(
    r"NVIDIA Announces Financial Results for (First|Second|Third|Fourth) Quarter( and)? Fiscal (20\d{2})",
    re.IGNORECASE,
)
OUTLOOK = re.compile(
    r"^NVIDIA['’]s outlook for the (first|second|third|fourth) quarter of fiscal (20\d{2}) is as follows:$",
    re.IGNORECASE | re.MULTILINE,
)
NUMBER = r"\d{1,9}(?:\.\d{1,6})?"
AMOUNT = rf"\$({NUMBER}) (billion|million)"
REVENUE = re.compile(rf"^Revenue is expected to be {AMOUNT}, plus or minus ({NUMBER})%(?:\.|$)", re.IGNORECASE)
GAAP_MARGIN = re.compile(
    rf"^GAAP and non[-‑]GAAP gross margins are expected to be (?:both )?({NUMBER})%"
    rf"(?: and {NUMBER}%, respectively)?, plus or minus ({NUMBER}) basis points\b",
    re.IGNORECASE,
)


def results_period(title: str) -> tuple[str, int] | None:
    match = RESULTS_TITLE.fullmatch(title)
    if match and (match[1].lower() == "fourth" or not match[2]):
        return match[1].lower(), int(match[3])
    return None


def results_facts(story: dict, text: str) -> list[dict]:
    """Read the issuer's reported quarter; keep forecast figures separate."""
    if story.get("kind") != "company" or story.get("publisher_symbol") != "NVDA" or not (period := results_period(story["title"])):
        raise ValueError("Nvidia results need the issuer and fiscal-quarter title")
    from src.intelligence.earnings_watch import NVIDIA_REVENUE, NVIDIA_MARGIN
    reported = []
    for match in NVIDIA_REVENUE.finditer(text):
        ended = re.search(r"ended [A-Za-z]+ \d{1,2}, (20\d{2})", match[0])
        if match[1].lower() != period[0] + " quarter" or not ended or int(ended[1]) != period[1] - (period[0] != "fourth"):
            continue
        if not re.fullmatch(r"\$(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)? (?:billion|million)", match[2], re.I):
            continue
        reported.append(match)
    if len({match[2] for match in reported}) != 1:
        raise ValueError("A unique reported Nvidia revenue for this fiscal quarter is required")
    match = reported[0]
    revenue, quote = match[2], match[0]
    label = period[0] + " quarter fiscal " + str(period[1])
    result = [{"field": "reported_revenue", "value": revenue + " (" + label + ", reported)", "evidence": quote}]
    # Bind the margin to the current result paragraph before the outlook.
    end = text.find("\n", match.end())
    section = text[match.end():end if end >= 0 else len(text)]
    margins = [(next(value for value in match.groups() if value is not None), match[0]) for match in NVIDIA_MARGIN.finditer(section)]
    if len({value for value, _ in margins}) == 1 and -100 <= Decimal(margins[0][0]) <= 100:
        value, quote = margins[0]
        result.append({"field": "reported_gross_margin", "value": value + "% (GAAP, " + label + ")", "evidence": quote})
    return result


def results_review(profile: dict) -> dict:
    fields = {row["field"]: row["value"] for row in profile["facts"]}
    revenue = fields["reported_revenue"].split(" (", 1)[0]
    period = fields["reported_revenue"].split(" (", 1)[1].removesuffix(", reported)")
    text = "Nvidia reported " + period + " revenue of " + revenue + "."
    if "reported_gross_margin" in fields:
        text += " Its GAAP gross margin was " + fields["reported_gross_margin"].split("%", 1)[0] + " percent."
    return {"evidence": profile, "facts": text,
            "why": "Revenue shows the scale of demand; gross margin shows how much remains after the cost of sales.",
            "watch": "Compare these results with original guidance, then check the next-quarter revenue and margin outlook."}


def preceding_release(period: tuple[str, int]) -> tuple[str, str]:
    quarter, fiscal_year = period
    index = QUARTERS.index(quarter)
    previous = QUARTERS[index - 1]
    year = fiscal_year - int(index == 0)
    conjunction = " and" if previous == "fourth" else ""
    title = f"NVIDIA Announces Financial Results for {previous.title()} Quarter{conjunction} Fiscal {year}"
    url = "https://nvidianews.nvidia.com/news/" + title.lower().replace(" ", "-")
    return title, url


def outlook_excerpt(text: str, period: tuple[str, int]) -> str:
    matches = list(OUTLOOK.finditer(text))
    if len(matches) != 1 or (matches[0][1].lower(), int(matches[0][2])) != period:
        raise ValueError("Original Nvidia outlook does not name the reported fiscal quarter")
    lines = text[matches[0].end():].strip().splitlines()
    # The company's quarter guidance starts with these two metrics. Keep only
    # the heading and complete metric rows, excluding full-year commentary.
    rows = [line for line in lines[:4] if REVENUE.match(line) or GAAP_MARGIN.match(line)]
    excerpt = "\n".join([matches[0][0], *rows])
    if not rows or len(excerpt) > 1200:
        raise ValueError("Original revenue or GAAP margin outlook missing")
    return excerpt


def decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def format_range(low: Decimal, high: Decimal, units: str) -> str:
    if units == "percent":
        return f"{decimal_text(low)} to {decimal_text(high)} percent"
    return f"${decimal_text(low)} {units} to ${decimal_text(high)} {units}"


def guidance_ranges(excerpt: str, period: tuple[str, int]) -> dict:
    if outlook_excerpt(excerpt, period) != excerpt:
        raise ValueError("Nvidia outlook excerpt changed")
    ranges = {}
    for line in excerpt.splitlines()[1:]:
        if match := REVENUE.match(line):
            field = "revenue"
            center = Decimal(match[1])
            spread = center * Decimal(match[3]) / 100
            units = match[2].lower()
        else:
            match = GAAP_MARGIN.match(line)
            field = "gaap_margin"
            center = Decimal(match[1])
            spread = Decimal(match[2]) / 100
            units = "percent"
        if field in ranges:
            raise ValueError("Nvidia outlook repeats the same guided metric")
        ranges[field] = (center - spread, center + spread, units)
    return ranges


def checked(proof: dict, period: tuple[str, int], previewed_at: datetime, now: datetime) -> dict:
    title, url = preceding_release(period)
    observed = timestamp(proof["observed"])
    published = date.fromisoformat(proof["published_date"])
    excerpt = proof["outlook"]
    if (proof["schema"] != 1 or proof["title"] != title or proof["url"] != url
            or published >= previewed_at.date() or observed is None
            or not -60 <= (now - observed).total_seconds() <= 21600
            or observed.date() < published or len(excerpt) > 1200
            or proof["sha256"] != sha256(excerpt.encode()).hexdigest()):
        raise ValueError("Original Nvidia guidance identity or observation is invalid")
    guidance_ranges(excerpt, period)
    return proof


def capture(story: dict, previewed_at: datetime, now: datetime, fetch) -> dict | None:
    period = results_period(story["title"]) if story.get("publisher_symbol") == "NVDA" else None
    if not period:
        return None
    title, url = preceding_release(period)
    response = fetch(url)
    final = response.get("final_url", response.get("url", ""))
    body = response.get("body")
    if (response.get("status") != "ok" or response.get("url") != url or final.rstrip("/") != url
            or not isinstance(body, str) or len(body.encode()) > 2_000_000):
        raise ValueError("Original Nvidia guidance page unavailable")
    page = PublicationPage()
    page.feed(body)
    if sum(heading.casefold() == title.casefold() for heading in page.headings) != 1:
        raise ValueError("Original Nvidia guidance heading does not match its release")
    article = ArticleBody("Nvidia Newsroom", url)
    article.feed(body)
    lines = [" ".join(line.split()) for line in "".join(article.parts).splitlines() if line.strip()]
    date_parts = " ".join("".join(article.date_parts).split())
    dates = {datetime.strptime(line, "%B %d, %Y").date()
             for line in (date_parts, *lines[:8]) if re.fullmatch(r"[A-Za-z]+ \d{1,2}, 20\d{2}", line)}
    if len(dates) > 1:
        raise ValueError("Original Nvidia guidance page has conflicting release dates")
    published = dates.pop() if dates else publication_time(body.encode(), title, url=url).date()
    excerpt = outlook_excerpt("\n".join(lines), period)
    observed = datetime.fromtimestamp(response["fetched_at_epoch"], timezone.utc)
    proof = {"schema": 1, "title": title, "url": url, "published_date": published.isoformat(),
             "observed": observed.isoformat(), "outlook": excerpt, "sha256": sha256(excerpt.encode()).hexdigest()}
    return checked(proof, period, previewed_at, now)


def comparisons(proof: dict, reported: dict, period: tuple[str, int]) -> dict:
    results = {}
    for field, (low, high, units) in guidance_ranges(proof["outlook"], period).items():
        actual = reported.get(field)
        if actual is None:
            continue
        if units == "percent":
            number = Decimal(actual)
            actual = f"{actual} percent"
        else:
            parsed = re.fullmatch(AMOUNT, actual.replace(",", ""), re.IGNORECASE)
            if not parsed:
                continue
            number = Decimal(parsed[1])
            if parsed[2].lower() != units:
                number = number / 1000 if units == "billion" else number * 1000
        position = "below" if number < low else "above" if number > high else "within"
        results[field] = {"actual": actual, "range": format_range(low, high, units), "position": position}
    return results


def next_range(text: str, period: tuple[str, int], field: str) -> str:
    quarter, year = period
    index = QUARTERS.index(quarter) + 1
    upcoming = QUARTERS[index % 4], year + int(index == 4)
    try:
        excerpt = outlook_excerpt(text, upcoming)
        bounds = guidance_ranges(excerpt, upcoming).get(field)
    except ValueError:
        return ""
    return format_range(*bounds) if bounds else ""
