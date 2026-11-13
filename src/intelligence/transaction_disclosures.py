"""Select dated watchlist transactions for the Daily Brief from existing caches."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from math import isfinite
import re
from typing import NamedTuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from src.intelligence import transaction_cache
from src.congress import congress_data as congress


HEADER = "Insider and Congressional Disclosures"
LANES = ("sec", "congress")
LABELS = {"sec": "SEC Form 4", "congress": "Congressional disclosures"}
CONGRESS_PROVIDERS = congress.CONGRESS_PROVIDERS
CACHE_AGE = congress.CACHE_MAX_AGE
MAX_ROWS = transaction_cache.MAX_ROWS
NY = ZoneInfo("America/New_York")
SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")
MONEY = r"(?:[0-9]{1,11}|[0-9]{1,3}(?:,[0-9]{3}){1,3})"
MONEY_RANGE = re.compile(rf"\$({MONEY})\s*[-–—]\s*\$({MONEY})")


def label(value, limit):
    if not isinstance(value, str) or not 0 < len(value) <= limit:
        return ""
    value = " ".join(value.split())
    return value if re.fullmatch(r"[^\W_][\w .,'’&()/%-]*", value) else ""


def day(value):
    if isinstance(value, str) and len(value) == 10:
        return date.fromisoformat(value)
    raise ValueError("Expected a calendar date")


def provider_day(value):
    from src.congress.congress_data import parse_date_value

    if not isinstance(value, str) or len(value) > 25:
        raise ValueError("Missing provider date")
    parsed = parse_date_value(value)
    if parsed == datetime.min:
        raise ValueError("Unrecognized provider date")
    return parsed.date()


def number(value):
    if type(value) not in (int, float) or not 0 <= value <= 10**12 or not isfinite(value):
        raise ValueError("Invalid disclosed quantity")
    return value


def filing_path(value, host):
    if not isinstance(value, str) or not 0 < len(value) <= 260 or not value.isascii():
        raise ValueError("Invalid filing link")
    parsed = urlsplit(value)
    if (not value.startswith("https://" + host + "/") or parsed.netloc != host
            or parsed.query or parsed.fragment or not re.fullmatch(r"/[\w./-]+", parsed.path)
            or ".." in parsed.path or value != "https://" + host + parsed.path):
        raise ValueError("A direct official filing link is required")
    return parsed.path


def sec_fields(raw):
    cik, accession = raw.get("cik"), raw.get("accession")
    if (not isinstance(cik, str) or not re.fullmatch(r"\d{1,10}", cik, re.ASCII) or not int(cik)
            or not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession, re.ASCII)):
        raise ValueError("Missing SEC filing identity")
    path = filing_path(raw.get("url"), "www.sec.gov")
    prefix = f"/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    if not path.startswith(prefix) or not path.endswith((".xml", ".htm", ".html", ".txt")):
        raise ValueError("SEC filing link disagrees with its accession")
    form, action = raw.get("form"), raw.get("transaction_code")
    if (form not in ("4", "4/A") or raw.get("source") != "SEC Form 4" or raw.get("security_type") != "Non-Derivative"
            or raw.get("ownership") != "D" or (action, raw.get("acquired_disposed")) not in (("P", "A"), ("S", "D"))):
        raise ValueError("Expected a reported direct non-derivative purchase or sale")
    person = label(raw.get("insider_name"), 64)
    if not person or person.casefold() in {"unknown", "unknown insider"}:
        raise ValueError("Missing SEC reporting owner")
    shares, price = number(raw.get("shares")), number(raw.get("price"))
    if not 0 < shares * price <= 10**11:
        raise ValueError("Missing SEC transaction value")
    remaining = raw.get("shares_owned_after")
    planned = raw.get("rule_10b5_1", False)
    if type(planned) is not bool:
        raise ValueError("Invalid trading plan flag")
    return {"cik": cik, "accession": accession, "form": form, "transaction_code": action,
            "acquired_disposed": raw["acquired_disposed"], "source": raw["source"], "security_type": raw["security_type"],
            "ownership": "D", "insider_name": person, "role": label(raw.get("role"), 48), "shares": shares, "price": price,
            "shares_owned_after": number(remaining) if remaining is not None else None,
            "rule_10b5_1": planned, "filing_date": day(raw.get("filing_date")).isoformat(), "url": raw["url"]}


def scope(lane, raw):
    if lane == "sec":
        cik = raw.get("cik")
        return cik.zfill(10) if isinstance(cik, str) and re.fullmatch(r"[0-9]{1,10}", cik) and int(cik) else None
    return congress.congress_chamber(raw.get("chamber"))


def congress_fields(raw):
    chamber = scope("congress", raw)
    if chamber == "House":
        path = filing_path(raw.get("source_url"), "disclosures-clerk.house.gov")
        if not re.fullmatch(r"/public_disc/ptr-pdfs/20[0-9]{2}/[0-9]{5,12}\.pdf", path):
            raise ValueError("A direct House periodic transaction report is required")
    elif chamber == "Senate":
        path = filing_path(raw.get("source_url"), "efdsearch.senate.gov")
        if not re.fullmatch(r"/search/view/ptr/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}/?", path):
            raise ValueError("A direct Senate periodic transaction report is required")
    else:
        raise ValueError("Missing congressional chamber")
    person = label(raw.get("politician"), 64)
    if not person or person.casefold() == "unknown" or raw.get("transaction") not in ("Purchase", "Sale"):
        raise ValueError("Missing filer or transaction direction")
    asset_type = label(raw.get("asset_type"), 48)
    description = label(raw.get("sector"), 180)
    if asset_type.casefold() not in {"stock", "common stock", "ordinary shares", "adr", "ads", "st"} and (
            asset_type or not re.search(r"\b(?:common stock|ordinary shares|depositary shares)\b", description, re.I)):
        raise ValueError("The provider row must identify an equity transaction")
    amount = raw.get("amount_range")
    bounds = MONEY_RANGE.fullmatch(amount.strip()) if isinstance(amount, str) and len(amount) < 50 else None
    if not bounds:
        raise ValueError("Missing congressional dollar range")
    low, high = [int(value.replace(",", "")) for value in bounds.groups()]
    if not 0 < low < high <= 10**10:
        raise ValueError("Invalid congressional dollar range")
    owner = label(raw.get("owner"), 32).casefold()
    owner = {"sp": "spouse", "dc": "dependent child", "jt": "joint"}.get(owner, owner)
    if owner not in {"self", "spouse", "dependent child", "joint"}:
        owner = "unknown"
    return {"chamber": chamber, "politician": person, "transaction": raw["transaction"], "asset_type": asset_type,
            "sector": description, "owner": owner, "amount_range": f"${low:,} - ${high:,}",
            "disclosure_date": provider_day(raw.get("disclosure_date")).isoformat(), "source_url": raw["source_url"]}


def normalized(raw, lane, today, observed_day):
    if not isinstance(raw, dict) or not isinstance(raw.get("ticker"), str) or not SYMBOL.fullmatch(raw["ticker"]):
        raise ValueError("Missing transaction ticker")
    if lane == "sec":
        trade = day(raw.get("transaction_date"))
        fields = sec_fields(raw)
        filed, max_trade_age = day(fields["filing_date"]), 30
    else:
        trade = provider_day(raw.get("transaction_date"))
        fields = congress_fields(raw)
        filed, max_trade_age = day(fields["disclosure_date"]), congress.MAX_TRADE_AGE.days
    if not 0 <= (today - filed).days < 7 or not trade <= filed <= observed_day or (today - trade).days > max_trade_age:
        raise ValueError("Outside the transaction or filing window")
    return {"ticker": raw["ticker"], "transaction_date": trade.isoformat(),
            "company": label(raw.get("company"), 48) or raw["ticker"], **fields}


def stake_fraction(row):
    """Calculate a line-item fraction only for a single standalone sale or purchase."""
    if row.get("related_exercise") or row.get("sale_count", 1) > 1:
        return None
    after = row["shares_owned_after"]
    shares = row["shares"]
    if after is None:
        return None
    before = after + shares if row["transaction_code"] == "S" else after - shares
    return shares / before if before > 0 else None


def priority(row, lane):
    if lane == "congress":
        low = int(MONEY_RANGE.fullmatch(row["amount_range"])[1].replace(",", ""))
        if low >= 15001:
            return row["disclosure_date"], low, row["transaction_date"]
        return None
    amount = row.get("gross_sale_value", row["shares"] * row["price"])
    fraction = stake_fraction(row) or 0
    purchase = row["transaction_code"] == "P"
    if amount >= (100000 if purchase else 1000000) or (not purchase and amount >= 100000 and fraction >= .10 and not row["rule_10b5_1"]):
        return row["filing_date"], purchase, not row["rule_10b5_1"], amount
    return None


class FilingSale(NamedTuple):
    related_exercise: bool
    sales: tuple


def filing_sales(raw_rows):
    """Group same-day direct sale and exercise rows by filer and accession."""
    groups = defaultdict(list)
    for raw in raw_rows:
        if (raw.get("security_type") == "Non-Derivative" and raw.get("ownership") == "D"
                and raw.get("transaction_code") in ("M", "S")):
            key = sale_key(raw)
            if all(key[:4]):
                groups[key].append(raw)
    result = {}
    for key, group in groups.items():
        exercise = any(raw["transaction_code"] == "M" and raw.get("acquired_disposed") == "A" for raw in group)
        sales = set()
        for raw in group:
            if raw["transaction_code"] != "S" or raw.get("acquired_disposed") != "D":
                continue
            try:
                shares, price = number(raw.get("shares")), number(raw.get("price"))
            except ValueError:
                continue
            if shares and price:
                holding = raw.get("shares_owned_after")
                holding = holding if isinstance(holding, (int, float)) and isfinite(holding) else -1
                sales.add((shares, price, holding))
        if sales:
            result[key] = FilingSale(exercise, tuple(sorted(sales)))
    return result


def sale_key(row):
    return (scope("sec", row), label(row.get("accession"), 20), label(row.get("insider_name"), 64).casefold(),
            label(row.get("transaction_date"), 10), label(row.get("security_title"), 100).casefold())


def sale_fields(context):
    total = round(sum(shares * price for shares, price, _ in context.sales), 2)
    if not 0 < total <= 10**11 or len(context.sales) > 100:
        raise ValueError("Form 4 sale values exceed the review limits")
    return {"related_exercise": context.related_exercise, "sale_count": len(context.sales),
            "gross_sale_value": total, "sale_components": [list(component) for component in context.sales]}


def unambiguous_sec_rows(rows):
    """Set aside overlapping amendments whose transaction lines disagree."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["cik"].lstrip("0"), row["insider_name"].casefold(), row["transaction_date"])].append(row)
    for group in groups.values():
        amendments = [row for row in group if row["form"] == "4/A"]
        accessions = {row["accession"] for row in group}
        if not amendments or len(accessions) == 1:
            yield from group
        elif len({tuple(row[key] for key in ("transaction_code", "shares", "price", "shares_owned_after", "rule_10b5_1")) for row in group}) == 1:
            yield max(amendments, key=lambda row: (row["filing_date"], row["accession"]))


def observed_at(value):
    if type(value) not in (int, float) or not 0 < value < 4102444800:
        raise ValueError("Invalid cache observation clock")
    return datetime.fromtimestamp(int(value), timezone.utc)


def scope_observations(lane, payload, now):
    valid_providers = ("SEC Form 4",) if lane == "sec" else tuple(CONGRESS_PROVIDERS.values())
    if "observations" in payload:
        observations = payload["observations"]
        if not isinstance(observations, dict) or len(observations) > 256:
            return {}
    else:
        source = payload.get("source")
        provider = source if lane == "sec" else CONGRESS_PROVIDERS.get(source) if isinstance(source, str) else None
        stamp = payload.get("cached_at" if lane == "sec" else "fetched_at")
        observations = {key: {"provider": provider, "at": stamp} for row in transaction_cache.rows(payload)
                        if (key := scope(lane, row))}
    result = {}
    for key, value in observations.items():
        if (not isinstance(value, dict) or value.get("provider") not in valid_providers
                or scope(lane, {"cik": key, "chamber": key}) != key):
            continue
        try:
            clock = observed_at(value.get("at"))
        except ValueError:
            continue
        if clock <= now:
            result[key] = {"at": clock.timestamp(), "provider": value["provider"]}
    if lane == "congress" and result:
        record_days = {key: observed_at(value["at"]).astimezone(NY).date() for key, value in result.items()}
        supported = {key for row in transaction_cache.rows(payload) if (key := scope(lane, row)) in record_days
                     and congress.recently_filed(row, record_days[key])}
        result = {key: value for key, value in result.items() if key in supported}
    return result


def cache_review(lane, path, now, companies):
    review = {"status": "unavailable", "provider": "", "observed_at": "", "reviewed": 0, "eligible": 0, "lead": None}
    try:
        payload, _ = transaction_cache.read(path)
        observations = scope_observations(lane, payload, now)
    except (OSError, ValueError, TypeError, OverflowError):
        return review
    if not observations:
        return review
    latest = max(observations.values(), key=lambda row: row["at"])
    latest_clock = observed_at(latest["at"])
    review.update(provider=latest["provider"], observed_at=latest_clock.isoformat(), status="stale" if now - latest_clock > CACHE_AGE else "current")
    if review["status"] == "stale":
        return review
    today = now.astimezone(NY).date()
    rows = []
    observations_by_row = {}
    raw_rows = transaction_cache.rows(payload)
    sale_contexts = filing_sales(raw_rows) if lane == "sec" else {}
    for raw in raw_rows:
        observation = observations.get(scope(lane, raw))
        if not observation or now - observed_at(observation["at"]) > CACHE_AGE:
            continue
        review["reviewed"] += 1
        if not isinstance(raw.get("ticker"), str) or raw["ticker"] not in companies:
            continue
        try:
            row = normalized({**raw, "company": companies[raw["ticker"]]}, lane, today, observed_at(observation["at"]).astimezone(NY).date())
        except (ValueError, TypeError):
            continue
        if lane == "sec" and row["transaction_code"] == "S":
            context = sale_contexts.get(sale_key(raw))
            if context and (context.related_exercise or len(context.sales) > 1):
                try:
                    row.update(sale_fields(context))
                except ValueError:
                    continue
        identity = json.dumps(row, sort_keys=True)
        if identity not in observations_by_row:
            observations_by_row[identity] = observation
            rows.append(row)
    if lane == "sec":
        rows = unambiguous_sec_rows(rows)
    eligible = [(key, row) for row in rows if (key := priority(row, lane)) is not None]
    if eligible:
        lead = max(eligible, key=lambda item: (item[0], item[1]["ticker"], json.dumps(item[1], sort_keys=True)))[1]
        source = observations_by_row[json.dumps(lead, sort_keys=True)]
        review.update(lead=lead, observed_at=observed_at(source["at"]).isoformat(), provider=source["provider"])
    review["eligible"] = len(eligible)
    return review


def capture(now):
    from src.congress import congress_data
    from src.insiders import insider_data
    from src.intelligence.company_focus import COMPANY_NAMES
    from src.scoring.watchlist import WATCHLIST

    companies = {row["ticker"]: COMPANY_NAMES.get(row["ticker"], row["ticker"])
                 for row in WATCHLIST if "ETF" not in row["category"].upper()}
    return {"schema": 3, "sec": cache_review("sec", insider_data.CACHE_FILE, now, companies),
            "congress": cache_review("congress", congress_data.CACHE_FILE, now, companies)}


def checked(profile, now):
    if not isinstance(profile, dict) or set(profile) != {"schema", *LANES} or type(profile["schema"]) is not int or profile["schema"] not in {1, 2, 3}:
        raise ValueError("Unknown daily transaction disclosure schema")
    for lane in LANES:
        review = profile[lane]
        if not isinstance(review, dict) or set(review) != {"status", "provider", "observed_at", "reviewed", "eligible", "lead"}:
            raise ValueError("Invalid disclosure coverage record")
        status, provider, stamp = review["status"], review["provider"], review["observed_at"]
        scanned, eligible, lead = review["reviewed"], review["eligible"], review["lead"]
        if type(scanned) is not int or type(eligible) is not int or not 0 <= eligible <= scanned <= MAX_ROWS:
            raise ValueError("Invalid disclosure review counts")
        if status == "unavailable" and not any((provider, stamp, scanned, eligible)) and lead is None:
            continue
        if provider not in (("SEC Form 4",) if lane == "sec" else tuple(CONGRESS_PROVIDERS.values())) or not isinstance(stamp, str):
            raise ValueError("Unknown transaction source")
        observed = datetime.fromisoformat(stamp)
        if observed.tzinfo is None or observed > now or status != ("stale" if now - observed > CACHE_AGE else "current"):
            raise ValueError("Transaction source observation disagrees with the edition clock")
        if status == "stale" and (scanned or eligible or lead is not None) or (profile["schema"] == 1 and status == "current" and not scanned):
            raise ValueError("Transaction source freshness disagrees with the review")
        if (lead is None) != (eligible == 0):
            raise ValueError("Transaction lead does not meet the daily brief screen")
        if lead is not None:
            expected = normalized(lead, lane, now.astimezone(NY).date(), observed.astimezone(NY).date())
            if lane == "sec" and profile["schema"] >= 3 and expected["transaction_code"] == "S" and "sale_components" in lead:
                related = lead.get("related_exercise")
                components = lead["sale_components"]
                if type(related) is not bool or not isinstance(components, list) or not 1 <= len(components) <= min(100, scanned):
                    raise ValueError("Form 4 sale context is invalid")
                sales = set()
                for component in components:
                    if not isinstance(component, list) or len(component) != 3:
                        raise ValueError("Form 4 sale component is invalid")
                    shares, price, holding = component
                    if not (number(shares) and number(price)):
                        raise ValueError("Form 4 sale component needs shares and price")
                    sales.add((shares, price, -1 if holding == -1 else number(holding)))
                reference = expected["shares"], expected["price"], expected["shares_owned_after"] if expected["shares_owned_after"] is not None else -1
                if reference not in sales or not (related or len(sales) > 1):
                    raise ValueError("Form 4 sale context lost its original line item")
                expected.update(sale_fields(FilingSale(related, tuple(sorted(sales)))))
            if expected != lead or priority(lead, lane) is None:
                raise ValueError("Transaction lead does not meet the daily brief screen")
    return profile


def brief_day(value):
    value = day(value)
    return f"{value:%B} {value.day}"


def display_company(row):
    return row["ticker"] if row["ticker"] == row["company"] else f"{row['company']} ({row['ticker']})"


def short_value(amount):
    if amount >= 10**6:
        return f"${amount / 10**6:.2f}".rstrip("0").rstrip(".") + " million"
    return f"${amount:,.0f}"


def sec_copy(row, schema=3):
    purchase = row["transaction_code"] == "P"
    trade = "purchase" if purchase else "sale"
    filed = brief_day(row["filing_date"])
    actor = row["insider_name"]
    if row["role"] and row["role"].casefold() != "insider":
        actor += " (" + row["role"] + ")"
    amount = short_value(row.get("gross_sale_value", row["shares"] * row["price"]))
    form = "Form 4 amendment" if row["form"] == "4/A" else "Form 4"
    trade_text = f"{row['sale_count']} sales on {brief_day(row['transaction_date'])} totaling about {amount} in gross proceeds" if row.get("sale_count", 1) > 1 else f"a {brief_day(row['transaction_date'])} {trade} worth about {amount}"
    text = f"{display_company(row)} — A {form} for {actor}, filed {filed}, reports {trade_text}."
    if row.get("related_exercise"):
        text += " The filing also reports same-day exercises or conversions of derivative securities."
    fraction = stake_fraction(row)
    if row["rule_10b5_1"]:
        return text + " The filing indicates use of a trading plan."
    if fraction is not None and 0.01 <= fraction <= 10 and row.get("sale_count", 1) == 1:
        change = "raised" if purchase else "reduced"
        if purchase or schema < 3:
            return text + f" The {trade} {change} the reported direct holding by about {fraction:.0%}."
        return text + f" The shares sold equal about {fraction:.0%} of the implied direct holding immediately before that line item."
    if row.get("related_exercise"):
        return text
    return text + " Watch for another reporting owner to make a similar trade."


def congress_copy(row, provider):
    lag = (day(row["disclosure_date"]) - day(row["transaction_date"])).days
    owner = {"self": "personal holding", "spouse": "spouse's holding", "dependent child": "dependent child's holding",
             "joint": "joint holding", "unknown": "owner unspecified in the feed"}[row["owner"]]
    timing = "disclosed the same day" if lag == 0 else f"disclosed {lag} {'day' if lag == 1 else 'days'} later"
    amount = row["amount_range"].replace(" - ", " to ")
    follow_up = (" Later filings can show whether purchases continued." if row["transaction"] == "Purchase"
                 else " Later filings can show whether sales continued.")
    return (f"{provider} lists a {row['chamber']} disclosure from {row['politician']} for a {brief_day(row['transaction_date'])} "
            f"{display_company(row)} {row['transaction'].lower()} of {amount} ({owner}), {timing} on {brief_day(row['disclosure_date'])}."
            + follow_up)


def paragraphs(profile):
    output = []
    for lane in LANES:
        review = profile[lane]
        lead = review["lead"]
        if lead is not None:
            output.append(sec_copy(lead, profile["schema"]) if lane == "sec" else congress_copy(lead, review["provider"]))
        elif review["status"] == "current":
            output.append(f"{LABELS[lane]} — No watchlist trade in the current feed met the brief's size, timing and source checks.")
        else:
            output.append(f"{LABELS[lane]} — {'The last source check is stale' if review['status'] == 'stale' else 'Current source data are unavailable'}.")
    return output


def validate_section(profile, report, now):
    from src.reports.daily_news_brief import ALL_HEADERS

    lines = report.splitlines()
    if profile is None:
        if HEADER in lines:
            raise ValueError("The transaction disclosure section has no retained evidence")
        return
    checked(profile, now)
    if lines.count(HEADER) != 1:
        raise ValueError("The edition needs one transaction disclosure section")
    start = lines.index(HEADER) + 1
    end = next((i for i in range(start, len(lines)) if lines[i] in ALL_HEADERS), len(lines))
    if "\n".join(lines[start:end]).strip() != "\n\n".join(paragraphs(profile)):
        raise ValueError("Transaction disclosure wording does not match the retained evidence")


def sources(profile):
    refs = {}
    for lane in LANES:
        review = profile[lane]
        lead = review["lead"]
        if lead is None:
            continue
        corporate = lane == "sec"
        refs["transactions_" + lane] = [{"url": lead["url" if corporate else "source_url"],
            "publisher": LABELS[lane] if corporate else f"{review['provider']} index of {lead['chamber']} disclosures",
            "published_at": lead["filing_date" if corporate else "disclosure_date"], "verified_at": review["observed_at"]}]
    return refs


def status_lines(profile):
    lines = [f"Transaction disclosure review: {profile['schema']}"]
    refs = sources(profile)
    for lane in LANES:
        review = profile[lane]
        stamp = " | checked " + review["observed_at"] if review["observed_at"] else ""
        lines.append(f"{LABELS[lane]} — {review['status']} | {review['eligible']} eligible / {review['reviewed']} cached rows reviewed" + stamp)
        for ref in refs.get("transactions_" + lane, []):
            lines.append(f"Filing for {review['lead']['ticker']} — {ref['publisher']} | {ref['url']}")
    return lines
