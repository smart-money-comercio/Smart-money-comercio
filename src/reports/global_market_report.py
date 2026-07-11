import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from src.scoring.scoring_engine import get_stock_scores


REQUEST_TIMEOUT = 6
MAX_HEADLINES = 8


MARKET_ASSETS = [
    {"name": "S&P 500", "symbol": "^GSPC", "type": "U.S. Market"},
    {"name": "Nasdaq", "symbol": "^IXIC", "type": "Growth / AI"},
    {"name": "Russell 2000", "symbol": "^RUT", "type": "Small Caps"},
    {"name": "VIX", "symbol": "^VIX", "type": "Volatility"},
    {"name": "Treasury Bonds", "symbol": "TLT", "type": "Rates"},
    {"name": "U.S. Dollar", "symbol": "UUP", "type": "Dollar"},
    {"name": "Gold", "symbol": "GLD", "type": "Safety / Inflation"},
    {"name": "Oil", "symbol": "USO", "type": "Energy"},
    {"name": "Emerging Markets", "symbol": "EEM", "type": "Global Risk"},
    {"name": "China", "symbol": "FXI", "type": "China"},
    {"name": "Europe", "symbol": "FEZ", "type": "Europe"},
    {"name": "Japan", "symbol": "EWJ", "type": "Japan"},
]


HEADLINE_FEEDS = [
    {
        "name": "Market",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
    },
    {
        "name": "Nasdaq",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EIXIC&region=US&lang=en-US",
    },
    {
        "name": "Rates",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=TLT&region=US&lang=en-US",
    },
    {
        "name": "Oil",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=USO&region=US&lang=en-US",
    },
    {
        "name": "Gold",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GLD&region=US&lang=en-US",
    },
]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any, max_length: int = 180) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def format_percent(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def get_asset_move(symbol: str) -> dict:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{encoded_symbol}?range=5d&interval=1d"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 SmartMoneyAI/1.0",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))

        result = payload.get("chart", {}).get("result", [])

        if not result:
            return {"symbol": symbol, "available": False}

        quote = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close") or []

        clean_closes = [
            safe_float(close, 0)
            for close in closes
            if safe_float(close, 0) > 0
        ]

        if len(clean_closes) < 2:
            return {"symbol": symbol, "available": False}

        latest = clean_closes[-1]
        previous = clean_closes[-2]
        change_percent = ((latest - previous) / previous) * 100 if previous else 0

        return {
            "symbol": symbol,
            "available": True,
            "latest": latest,
            "previous": previous,
            "change_percent": round(change_percent, 2),
        }

    except Exception:
        return {"symbol": symbol, "available": False}


def load_market_snapshot() -> list[dict]:
    snapshot = []

    for asset in MARKET_ASSETS:
        move = get_asset_move(asset["symbol"])
        snapshot.append({**asset, **move})

    return snapshot


def get_move(snapshot: list[dict], symbol: str) -> float:
    for item in snapshot or []:
        if item.get("symbol") == symbol and item.get("available"):
            return safe_float(item.get("change_percent"), 0)

    return 0.0


def classify_market_regime(snapshot: list[dict]) -> str:
    spx = get_move(snapshot, "^GSPC")
    nasdaq = get_move(snapshot, "^IXIC")
    rut = get_move(snapshot, "^RUT")
    vix = get_move(snapshot, "^VIX")
    tlt = get_move(snapshot, "TLT")
    dollar = get_move(snapshot, "UUP")
    oil = get_move(snapshot, "USO")

    if vix >= 5 and (spx < 0 or nasdaq < 0):
        return "Risk-Off / Volatility Rising"

    if spx > 0 and nasdaq > 0 and vix < 0:
        return "Risk-On / Growth Supported"

    if nasdaq < 0 and tlt < 0 and dollar > 0:
        return "Rates-Dollar Pressure on Growth"

    if oil >= 2:
        return "Energy / Inflation Pressure"

    if rut > spx and rut > nasdaq:
        return "Small-Cap Rotation"

    return "Mixed / Selective Market"


def classify_asset_signal(item: dict) -> str:
    if not item.get("available"):
        return "Unavailable"

    symbol = item.get("symbol")
    change = safe_float(item.get("change_percent"), 0)

    if symbol == "^VIX":
        if change >= 5:
            return "Volatility Rising"
        if change <= -5:
            return "Volatility Cooling"
        return "Volatility Stable"

    if change >= 2:
        return "Strong Up Move"
    if change >= 0.5:
        return "Positive"
    if change <= -2:
        return "Sharp Weakness"
    if change <= -0.5:
        return "Negative"

    return "Stable"


def fetch_rss_headlines(feed: dict, limit: int = 3) -> list[dict]:
    try:
        request = urllib.request.Request(
            feed["url"],
            headers={
                "User-Agent": "Mozilla/5.0 SmartMoneyAI/1.0",
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )

        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="ignore")

        root = ET.fromstring(raw)
        items = []

        for item in root.findall(".//item")[:limit]:
            title = clean_text(item.findtext("title"), 160)
            link = clean_text(item.findtext("link"), 240)

            if title:
                items.append(
                    {
                        "source": feed["name"],
                        "title": title,
                        "link": link,
                        "impact": classify_headline_impact(title),
                    }
                )

        return items

    except Exception:
        return []


def classify_headline_impact(title: str) -> str:
    text = title.lower()

    if any(word in text for word in ["fed", "rates", "yield", "treasury", "inflation", "cpi", "pce"]):
        return "Rates / Inflation"

    if any(word in text for word in ["oil", "crude", "energy", "opec"]):
        return "Energy"

    if any(word in text for word in ["china", "tariff", "trade", "export", "taiwan"]):
        return "China / Trade"

    if any(word in text for word in ["ai", "chip", "semiconductor", "nvidia", "nasdaq", "tech"]):
        return "AI / Tech"

    if any(word in text for word in ["war", "defense", "missile", "drone", "geopolitical"]):
        return "Defense / Geopolitical"

    if any(word in text for word in ["dollar", "gold", "safe haven"]):
        return "Dollar / Safety"

    return "Market"


def load_headlines() -> list[dict]:
    headlines = []

    for feed in HEADLINE_FEEDS:
        headlines.extend(fetch_rss_headlines(feed, limit=3))

    seen = set()
    deduped = []

    for item in headlines:
        title_key = item["title"].lower()

        if title_key in seen:
            continue

        seen.add(title_key)
        deduped.append(item)

        if len(deduped) >= MAX_HEADLINES:
            break

    return deduped


def get_portfolio_theme_counts(stocks: list[dict]) -> dict:
    counts = {
        "AI / Semiconductors": 0,
        "Cybersecurity": 0,
        "Defense": 0,
        "Energy / Infrastructure": 0,
        "Dividend / Defensive": 0,
        "Speculative": 0,
        "Other": 0,
    }

    for stock in stocks or []:
        category = clean_text(stock.get("category"), 160).upper()

        if "AI" in category or "SEMICONDUCTOR" in category or "DATA CENTER" in category:
            counts["AI / Semiconductors"] += 1
        elif "CYBER" in category:
            counts["Cybersecurity"] += 1
        elif "DEFENSE" in category or "DRONE" in category or "WARFARE" in category:
            counts["Defense"] += 1
        elif "ENERGY" in category or "POWER" in category or "GRID" in category or "INFRASTRUCTURE" in category:
            counts["Energy / Infrastructure"] += 1
        elif "DIVIDEND" in category or "INCOME" in category or "UTILITY" in category or "DEFENSIVE" in category:
            counts["Dividend / Defensive"] += 1
        elif "SPECULATIVE" in category or "HIGH RISK" in category or "EARLY" in category:
            counts["Speculative"] += 1
        else:
            counts["Other"] += 1

    return counts


def build_portfolio_impact(snapshot: list[dict], stocks: list[dict]) -> str:
    regime = classify_market_regime(snapshot)
    counts = get_portfolio_theme_counts(stocks)

    nasdaq = get_move(snapshot, "^IXIC")
    vix = get_move(snapshot, "^VIX")
    tlt = get_move(snapshot, "TLT")
    dollar = get_move(snapshot, "UUP")
    oil = get_move(snapshot, "USO")
    gold = get_move(snapshot, "GLD")
    china = get_move(snapshot, "FXI")
    eem = get_move(snapshot, "EEM")

    notes = []

    if nasdaq < -0.75 or (tlt < -0.75 and dollar > 0.5):
        notes.append(
            "Growth, AI, and semiconductor names may face pressure if rates or the dollar are rising."
        )

    if vix > 5:
        notes.append(
            "Volatility is rising, so speculative and high-beta names should be sized carefully."
        )

    if oil > 2:
        notes.append(
            "Oil strength can support energy names but may raise inflation pressure for the broader market."
        )

    if gold > 1:
        notes.append(
            "Gold strength suggests investors may be looking for safety or inflation protection."
        )

    if china < -1 or eem < -1:
        notes.append(
            "Weakness in China or emerging markets can pressure global cyclicals and risk appetite."
        )

    if not notes:
        notes.append(
            "No single macro pressure point is dominating. Portfolio decisions should stay selective."
        )

    exposure_text = "\n".join(
        f"- {theme}: {count}"
        for theme, count in counts.items()
        if count > 0
    )

    notes_text = "\n".join(f"- {note}" for note in notes)

    return f"""
Market Regime:
{regime}

Portfolio Theme Exposure:
{exposure_text if exposure_text else "- No portfolio themes found."}

Potential Portfolio Impact:
{notes_text}
""".strip()


def format_market_snapshot(snapshot: list[dict]) -> str:
    lines = []

    for item in snapshot or []:
        if not item.get("available"):
            lines.append(f"- {item['name']} ({item['symbol']}): Unavailable")
            continue

        lines.append(
            f"- {item['name']} ({item['symbol']}): "
            f"{format_percent(item.get('change_percent'))} | "
            f"{classify_asset_signal(item)}"
        )

    return "\n".join(lines) if lines else "Market snapshot unavailable."


def format_headlines(headlines: list[dict]) -> str:
    if not headlines:
        return "No macro headlines available right now."

    lines = []

    for item in headlines:
        lines.append(f"- [{item['impact']}] {item['title']}")

    return "\n".join(lines)


def build_global_risk_snapshot() -> str:
    try:
        snapshot = load_market_snapshot()
    except Exception:
        snapshot = []

    try:
        headlines = load_headlines()
    except Exception:
        headlines = []

    if not snapshot:
        return """
🌍 Global Risk Snapshot

Market Regime:
Unavailable

Portfolio Impact:
- Global market data could not be loaded right now.

Headline Themes:
- Headlines unavailable.

Use /global for the full macro risk report.
""".strip()

    regime = classify_market_regime(snapshot)

    nasdaq = get_move(snapshot, "^IXIC")
    vix = get_move(snapshot, "^VIX")
    tlt = get_move(snapshot, "TLT")
    dollar = get_move(snapshot, "UUP")
    oil = get_move(snapshot, "USO")
    gold = get_move(snapshot, "GLD")
    china = get_move(snapshot, "FXI")
    eem = get_move(snapshot, "EEM")

    impact_notes = []

    if nasdaq < -0.75 or (tlt < -0.75 and dollar > 0.5):
        impact_notes.append(
            "Growth, AI, and semiconductor names may face pressure from rates or dollar strength."
        )

    if vix > 5:
        impact_notes.append(
            "Volatility is rising; speculative names need tighter risk control."
        )

    if oil > 2:
        impact_notes.append(
            "Oil strength may support energy exposure but can raise inflation pressure."
        )

    if gold > 1:
        impact_notes.append(
            "Gold strength suggests investors may be seeking safety or inflation protection."
        )

    if china < -1 or eem < -1:
        impact_notes.append(
            "China or emerging-market weakness may pressure global risk appetite."
        )

    if not impact_notes:
        impact_notes.append(
            "No single global pressure point is dominating; stay selective."
        )

    headline_themes = []

    for item in headlines[:5]:
        impact = item.get("impact", "Market")

        if impact not in headline_themes:
            headline_themes.append(impact)

    if not headline_themes:
        headline_themes = ["No major headline theme available"]

    impact_text = "\n".join(f"- {note}" for note in impact_notes[:3])
    headline_text = ", ".join(headline_themes[:5])

    return f"""
🌍 Global Risk Snapshot

Market Regime:
{regime}

Portfolio Impact:
{impact_text}

Headline Themes:
{headline_text}

Use /global for the full macro risk report.
""".strip()


def build_global_market_report() -> str:
    try:
        stocks = get_stock_scores()
    except Exception:
        stocks = []

    try:
        snapshot = load_market_snapshot()
    except Exception:
        snapshot = []

    try:
        headlines = load_headlines()
    except Exception:
        headlines = []

    return f"""
🌍 Global Market Risk Monitor

Market Snapshot:
{format_market_snapshot(snapshot)}

Portfolio Impact:
{build_portfolio_impact(snapshot, stocks)}

Headline Watch:
{format_headlines(headlines)}

How To Use This:
- If volatility and the dollar rise together, reduce confidence in high-beta growth setups.
- If oil spikes, watch inflation-sensitive names and energy exposure.
- If gold rises while equities fall, risk appetite may be weakening.
- If Nasdaq leads and volatility cools, AI and growth setups may have better support.

Next Commands:
/top10
/smartmoney
/portfolio
/volume refresh
/report

Note:
This is research only, not financial advice.
""".strip()