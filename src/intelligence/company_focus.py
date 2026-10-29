"""Dated editorial company selection from report facts and admitted developments."""

from collections import Counter
from datetime import datetime
import hashlib
import math
import re
from zoneinfo import ZoneInfo

from src.config.theme_watchlist_universe import THEME_TICKERS
from src.intelligence.special_alert_sources import timestamp


NY = ZoneInfo("America/New_York")
COMPANY_NAMES = {
    "MSFT": "Microsoft", "NVDA": "Nvidia", "AMD": "Advanced Micro Devices", "AVGO": "Broadcom",
    "TSM": "Taiwan Semiconductor", "ASML": "ASML", "INTC": "Intel", "MU": "Micron", "ARM": "Arm",
    "MRVL": "Marvell", "SMCI": "Super Micro Computer", "PLTR": "Palantir", "TSLA": "Tesla",
    "AAPL": "Apple", "AMZN": "Amazon", "META": "Meta Platforms", "GOOG": "Alphabet", "GOOGL": "Alphabet",
    "SONY": "Sony", "ORCL": "Oracle", "LMT": "Lockheed Martin", "RTX": "RTX", "NOC": "Northrop Grumman", "GD": "General Dynamics",
    "LHX": "L3Harris", "HII": "Huntington Ingalls", "KTOS": "Kratos Defense", "AVAV": "AeroVironment",
    "LDOS": "Leidos", "CACI": "CACI International", "CRWD": "CrowdStrike",
    "XOM": "Exxon Mobil", "CVX": "Chevron", "COP": "ConocoPhillips", "SLB": "SLB", "HAL": "Halliburton",
    "OXY": "Occidental Petroleum", "EOG": "EOG Resources", "LNG": "Cheniere Energy",
    "VRT": "Vertiv", "ETN": "Eaton", "GEV": "GE Vernova", "CEG": "Constellation Energy",
    "NEE": "NextEra Energy", "SO": "Southern Company", "PWR": "Quanta Services", "EME": "EMCOR",
    "GNRC": "Generac", "APLD": "Applied Digital", "JPM": "JPMorgan Chase", "BAC": "Bank of America",
    "WFC": "Wells Fargo", "C": "Citigroup", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "AXP": "American Express", "COF": "Capital One", "ALLY": "Ally Financial", "SCHW": "Charles Schwab",
    "WMT": "Walmart", "COST": "Costco", "TGT": "Target", "HD": "Home Depot", "LOW": "Lowe's",
    "MCD": "McDonald's", "SBUX": "Starbucks", "V": "Visa", "MA": "Mastercard",
}
FUNDS = {"TLT", "IEF", "UUP", "GLD", "USO", "XLE", "SPY", "QQQ", "VOO", "SMH", "ITA"}


def issuer(symbol: str) -> str:
    return "GOOGL" if symbol == "GOOG" else symbol


def company(symbol) -> bool:
    return isinstance(symbol, str) and bool(re.fullmatch(r"[A-Z][A-Z0-9]{0,5}", symbol)) and symbol not in FUNDS


def history_context(now: datetime) -> dict:
    """Read recent built editions once; repeated builds today do not cause churn."""
    from src.intelligence.news_editor_store import read_editions
    today = now.astimezone(NY).date()
    days = {}
    try:
        records = read_editions(200)
    except Exception:
        records = []
    for record in records:
        at = timestamp(record.get("generated_at"))
        if at is None or not 1 <= (today-at.astimezone(NY).date()).days <= 7:
            continue
        evidence = (record.get("analyst_review") or {}).get("evidence", {})
        focus = evidence.get("company_focus", {})
        selected = [{"symbol": symbol} for symbol in focus["featured_symbols"]] if isinstance(focus.get("featured_symbols"), list) else focus.get("selected")
        if selected is None and any(row.get("id") == "ranking" for row in (record.get("analyst_review") or {}).get("insights", [])):
            selected = evidence.get("companies", [])[:3]
        symbols = {issuer(row.get("symbol")) for row in selected or [] if isinstance(row, dict) and company(row.get("symbol"))}
        if symbols:
            days.setdefault(at.astimezone(NY).date().isoformat(), set()).update(symbols)
    return {"schema": 3, "limit": 3, "recent": [{"day": day, "symbols": sorted(symbols)[:100]} for day, symbols in sorted(days.items())]}


def checked_context(context: dict, day) -> dict:
    if (not isinstance(context, dict) or set(context) != {"schema", "limit", "recent"} or type(context["schema"]) is not int or context["schema"] not in {1, 2, 3}
            or type(context["limit"]) is not int or not 1 <= context["limit"] <= 3
            or not isinstance(context["recent"], list) or len(context["recent"]) > 7):
        raise ValueError("Invalid company-focus context")
    seen = set()
    for row in context["recent"]:
        if not isinstance(row, dict) or set(row) != {"day", "symbols"}:
            raise ValueError("Invalid recent company-focus record")
        date = datetime.strptime(row["day"], "%Y-%m-%d").date()
        if (not 1 <= (day-date).days <= 7 or row["day"] in seen or not isinstance(row["symbols"], list)
                or len(row["symbols"]) > 100 or any(not company(value) for value in row["symbols"])):
            raise ValueError("Company-focus history needs distinct, earlier edition dates")
        seen.add(row["day"])
    return context


def select_focus(report: str, evidence: dict, context: dict) -> dict:
    from src.intelligence.market_brief import story_topics
    from src.reports.report_quality import split_report_sections
    sections = {key: "\n".join(lines[1:]) for key, lines in split_report_sections(report) if key}
    match = re.search(r"^Generated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+)$", report, re.M)
    if not match:
        raise ValueError("Company focus requires the edition's generation clock")
    day = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(match[2])).astimezone(NY).date()
    checked_context(context, day)
    counts = Counter(symbol for row in context["recent"] for symbol in {issuer(value) for value in row["symbols"]})
    pool = {}
    from src.intelligence.market_brief import story_topics
    covered_global = {issuer(symbol) for story in evidence.get("stories", []) if context["schema"] >= 2 and "defense" in story_topics(story)
                      for symbol in ([story["publisher_symbol"]] if company(story.get("publisher_symbol")) else story.get("symbols", []))}

    def add(symbol, group, role, tier, why, watch, sources, *, metric=None, story_id=""):
        if not company(symbol):
            return
        symbol = issuer(symbol)
        if symbol in covered_global:
            return
        value = {"symbol": symbol, "name": COMPANY_NAMES.get(symbol, symbol), "group": group, "role": role,
            "tier": tier, "why": why, "watch": watch, "sources": sources, "metric": metric,
            "story_id": story_id, "recent_days": counts[symbol]}
        if context["schema"] >= 3:
            from src.intelligence.broadcast_story import next_check
            value["basis"] = "company report" if story_id else "price move" if group == "price move" else "sector context"
            value["watch"] = next_check(watch)
        if symbol not in pool or (tier, bool(story_id)) > (pool[symbol]["tier"], bool(pool[symbol]["story_id"])):
            pool[symbol] = value

    try:
        session_day = datetime.strptime(evidence["session"], "%Y-%m-%d").date()
        dated_session = 0 <= (day-session_day).days <= 4
    except (TypeError, ValueError):
        dated_session = False
    moves, stories = evidence["moves"] if dated_session else {}, evidence.get("stories", [])
    for story in stories:
        if story.get("kind") != "company":
            continue
        topic = story.get("materiality", "company development")
        stage = story.get("event_evidence", {}).get("stage")
        why = "An original company report brings a fresh business development into focus."
        watch = "Watch the disclosed commitments, execution costs and any change to guidance."
        if stage in {"test milestone", "planned test", "prototype"}:
            why = "The reported technical milestone puts procurement and production readiness in focus."
            watch = "Watch repeat validation, funded orders and delivery costs."
        elif topic in {"earnings", "guidance"}:
            why = "The company's results or outlook put its demand and margin assumptions back in focus."
            watch = "Watch cash generation and delivery against management's guidance."
        elif topic == "acquisition":
            why = "The reported transaction puts financing and integration in focus."
            watch = "Watch disclosed costs, closing conditions and cash generation."
        subjects = [story["publisher_symbol"]] if company(story.get("publisher_symbol")) else story.get("symbols", [])
        for symbol in subjects:
            add(symbol, "company development", "Development to watch", 100, why, watch,
                ["Verified story decisions"], story_id=story["id"])

    if dated_session:
        prices = {row["symbol"]: row["price"] for row in evidence["companies"] if row.get("price") is not None}
        for symbol, raw in re.findall(r"^[•\-] (\w+): \$[\d,.]+ \(([+-]?\d+(?:\.\d+)?)%\)$", sections.get("Watchlist Movers", ""), re.M):
            value = float(raw)
            if math.isfinite(value) and -100 <= value <= 1000:
                prices[symbol] = value
        for symbol, value in prices.items():
            if symbol not in COMPANY_NAMES or abs(value) < 1.5:
                continue
            direction = "rose" if value > 0 else "fell"
            add(symbol, "price move", "Momentum watch" if value > 0 else "Risk watch", 70 + min(15, abs(value)*2),
                f"It {direction} {abs(value):.1f} percent in the quoted regular session.",
                "Watch whether volume and the next company disclosure support a lasting change in the setup.",
                ["Market Snapshot", "Watchlist Movers", "Top Opportunities"], metric={"price": value})

    def theme(key, group, role, why, watch, tier=60, metric=None):
        for symbol in THEME_TICKERS.get(key, []):
            add(symbol, group, role, tier, why, watch, ["Executive Summary", "Market Snapshot", "Research theme universe"], metric=metric)

    oil = moves.get("Oil")
    if oil is not None and abs(oil) >= 1.5:
        theme("Oil / Geopolitical Risk", "energy", "Energy spotlight",
            f"Oil {'rose' if oil > 0 else 'fell'} {abs(oil):.2f} percent in the quoted session, putting the energy business backdrop in focus.",
            "Watch realized pricing, customer investment decisions and cash flow after costs and capital spending.", metric={"Oil": oil})
    breadth = evidence.get("breadth")
    if moves.get("Nasdaq", 0) <= -1.5 or moves.get("VIX", 0) >= 5:
        theme("AI / Chips", "growth pressure", "Growth risk watch",
            "Pressure in the market indicators raises the bar for growth-company confirmation.",
            "Watch demand, margins and whether price and volume stabilize together.")
    if breadth and breadth["down"] > breadth["up"]:
        theme("Consumer Stress", "consumer", "Consumer watch",
            f"More names fell than rose in the {breadth['total']}-symbol quoted watchlist, putting resilience in focus.",
            "Watch consumer demand, pricing and operating margins in the next company update.")
    if moves.get("Nasdaq", 0) >= .5 and (not breadth or breadth["up"] >= breadth["down"]):
        theme("AI Infrastructure / Power", "infrastructure", "Infrastructure watch",
            "Improving growth-index support puts the AI infrastructure and power investment cycle in focus.",
            "Watch funded orders, power availability, delivery timing and cash requirements.")
    if (abs(moves.get("TLT", 0)) >= .75 or re.search(r"\[(?:Fed|BLS|BEA)\]", sections.get("Earnings & Economic Calendar", ""))
            or any("policy" in story_topics(story) for story in stories)):
        theme("Banks / Credit", "credit", "Credit and policy watch",
            "The rate-sensitive backdrop puts lending economics and funding conditions in focus.",
            "Watch loan demand, funding costs and credit losses; bond-price moves alone do not verify yields.")
    if any("defense" in story_topics(story) or "geopolitics" in story_topics(story) for story in stories):
        theme("Defense / AI Warfare", "defense", "Defense industry watch",
            "Verified defense or global-risk reports put the sector's execution pipeline in focus.",
            "Watch procurement approvals, funded backlog and the path from testing to production.")
    if moves or evidence["companies"] or stories:
        for key, group, role, watch in (
            ("AI / Chips", "technology", "Technology research watch", "Watch customer demand, commercial timing and cash generation."),
            ("Defense / AI Warfare", "defense", "Defense research watch", "Watch funded procurement and production milestones in original disclosures."),
            ("Consumer Stress", "consumer", "Consumer research watch", "Watch demand, pricing and margin trends in the next company update.")):
            theme(key, group, role, "This is a longer-term research follow-up while fresh company-specific confirmation remains the next check.", watch, tier=20)

    selected, used_groups = [], set()
    while pool and len(selected) < context["limit"]:
        def priority(row):
            tier = row["tier"] - (50 if row["tier"] < 100 and row["group"] in used_groups else 0)
            return (-tier, row["group"] in used_groups, row["recent_days"],
                hashlib.sha256((day.isoformat()+row["symbol"]).encode()).hexdigest())
        row = min(pool.values(), key=priority)
        selected.append(row); used_groups.add(row["group"]); del pool[row["symbol"]]
    featured = {row["symbol"] for row in selected}
    for story in stories:
        if story.get("kind") == "company" and "defense" not in story_topics(story):
            featured.update(issuer(symbol) for symbol in [story.get("publisher_symbol")] if company(symbol))
    return {"schema": 1, "day": day.isoformat(), "selected": selected, "featured_symbols": sorted(featured), "remaining_candidates": len(pool),
        "rule": "Original developments, dated moves and market relevance; recent exposure breaks comparable ties"}


def focus_paragraph(row: dict, stories: list[dict]) -> str:
    if row["story_id"]:
        story = next(value for value in stories if value["id"] == row["story_id"])
        from src.intelligence.market_brief import story_topics
        if "defense" not in story_topics(story):
            return ""  # The complete sourced story already appears in Companies in Focus.
    if row.get("basis"):
        qualifier = f" No fresh {row['name']} announcement is included in this edition." if row["basis"] == "sector context" else ""
        return f"{row['role']} — {row['name']}. {row['why']}{qualifier} {row['watch']}"
    return f"{row['role']} — {row['name']}. {row['why']} {row['watch']}"
