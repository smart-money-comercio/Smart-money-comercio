from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_MEMORY_PATH = DATA_DIR / "opportunity_score_memory.json"
NEWS_CACHE_PATH = DATA_DIR / "news_live_source_cache.json"

REPORT_TIMEZONE = "America/New_York"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)
    except Exception:
        return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def clean_symbol(value: Any) -> str:
    return str(value or "").upper().replace("$", "").strip()


def today_key() -> str:
    return datetime.now(ZoneInfo(REPORT_TIMEZONE)).strftime("%Y-%m-%d")


def get_structural_score(stock: dict) -> float:
    return safe_float(
        stock.get(
            "final_score",
            stock.get(
                "smart_money_score",
                stock.get("score", 0),
            ),
        )
    )


def mover_map(movers: list[dict]) -> dict[str, dict]:
    result = {}

    for item in movers or []:
        symbol = clean_symbol(item.get("symbol") or item.get("ticker"))

        if symbol:
            result[symbol] = item

    return result


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def extract_ticker_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    candidates = [
        value.get("tickers"),
        value.get("ticker_counts"),
    ]

    for parent_key in [
        "context",
        "summary",
        "latest",
        "data",
        "result",
    ]:
        child = value.get(parent_key)

        if isinstance(child, dict):
            candidates.extend(
                [
                    child.get("tickers"),
                    child.get("ticker_counts"),
                ]
            )

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        result = {}

        for symbol, count in candidate.items():
            clean = clean_symbol(symbol)

            if clean:
                result[clean] = int(safe_float(count, 0))

        if result:
            return result

    return {}


def load_news_ticker_counts(context: dict | None = None) -> dict[str, int]:
    context = context or {}

    direct = extract_ticker_counts(context)

    if direct:
        return direct

    cache = read_json(NEWS_CACHE_PATH)
    return extract_ticker_counts(cache)


def load_memory(path: Path = DEFAULT_MEMORY_PATH) -> dict:
    memory = read_json(path)

    if not memory:
        return {
            "current_date": "",
            "current": {},
            "previous_date": "",
            "previous": {},
        }

    return {
        "current_date": str(memory.get("current_date") or ""),
        "current": memory.get("current", {}) if isinstance(memory.get("current"), dict) else {},
        "previous_date": str(memory.get("previous_date") or ""),
        "previous": memory.get("previous", {}) if isinstance(memory.get("previous"), dict) else {},
    }


def previous_baseline(memory: dict, current_date: str) -> dict:
    if memory.get("current_date") == current_date:
        return memory.get("previous", {}) or {}

    return memory.get("current", {}) or {}


def save_memory(
    ranked: list[dict],
    path: Path = DEFAULT_MEMORY_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    current_date = today_key()
    existing = load_memory(path)

    snapshot = {}

    for item in ranked:
        symbol = clean_symbol(item.get("ticker") or item.get("symbol"))

        if not symbol:
            continue

        snapshot[symbol] = {
            "structural_score": round(get_structural_score(item), 2),
            "opportunity_score": round(
                safe_float(item.get("opportunity_score")),
                2,
            ),
        }

    if existing.get("current_date") == current_date:
        payload = {
            "current_date": current_date,
            "current": snapshot,
            "previous_date": existing.get("previous_date", ""),
            "previous": existing.get("previous", {}),
        }
    else:
        payload = {
            "current_date": current_date,
            "current": snapshot,
            "previous_date": existing.get("current_date", ""),
            "previous": existing.get("current", {}),
        }

    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def price_adjustment(change_percent: float | None) -> tuple[float, str]:
    if change_percent is None:
        return 0.0, "price confirmation unavailable"

    change = float(change_percent)

    if 0.75 <= change <= 3.5:
        return 2.0, f"constructive price strength {change:+.1f}%"

    if 3.5 < change <= 6.0:
        return 1.0, f"strong move {change:+.1f}% but becoming extended"

    if change > 6.0:
        return -1.5, f"extended move {change:+.1f}%; chase risk elevated"

    if -0.75 < change < 0.75:
        return 0.0, f"price roughly flat {change:+.1f}%"

    if -3.0 <= change <= -0.75:
        return -1.0, f"price confirmation weakened {change:+.1f}%"

    if -6.0 <= change < -3.0:
        return -2.0, f"meaningful downside move {change:+.1f}%"

    return -3.0, f"large downside move {change:+.1f}%"


def news_adjustment(count: int) -> tuple[float, str]:
    if count <= 0:
        return 0.0, "no fresh ticker news cluster"

    adjustment = min(count, 4) * 0.75

    return adjustment, f"{count} fresh ticker-news signal{'s' if count != 1 else ''}"


def volume_adjustment(stock: dict) -> tuple[float, str]:
    existing = safe_float(stock.get("volume_adjustment"), 0)

    if existing > 0:
        return existing, str(
            stock.get("volume_label")
            or "positive volume confirmation"
        )

    if existing < 0:
        return existing, str(
            stock.get("volume_label")
            or "weak volume confirmation"
        )

    return 0.0, str(
        stock.get("volume_label")
        or "volume neutral"
    )


def risk_adjustment(stock: dict) -> tuple[float, str]:
    label = str(stock.get("risk_label") or "").lower()

    if "speculative" in label:
        return -2.0, "speculative risk profile"

    if "high risk" in label or "elevated" in label:
        return -1.5, "elevated risk profile"

    if "controlled" in label:
        return 0.75, "controlled risk profile"

    return 0.0, "balanced risk profile"


def structural_change_adjustment(
    structural_score: float,
    previous_item: dict | None,
) -> tuple[float, float, str]:
    if not previous_item:
        return 0.0, 0.0, "no prior structural baseline"

    previous_score = safe_float(
        previous_item.get("structural_score"),
        structural_score,
    )

    delta = structural_score - previous_score

    adjustment = clamp(delta * 0.6, -3.0, 3.0)

    if abs(delta) < 0.05:
        return adjustment, delta, "structural score unchanged"

    return adjustment, delta, f"structural score {delta:+.1f} vs prior report"


def build_opportunity_item(
    stock: dict,
    mover: dict | None,
    news_count: int,
    previous_item: dict | None,
) -> dict:
    structural = get_structural_score(stock)

    price_change = None

    if mover:
        price_change = safe_float(
            mover.get("change_percent"),
            default=0,
        )

    price_adj, price_reason = price_adjustment(price_change)
    news_adj, news_reason = news_adjustment(news_count)
    volume_adj, volume_reason = volume_adjustment(stock)
    risk_adj, risk_reason = risk_adjustment(stock)

    structural_adj, structural_delta, structural_reason = (
        structural_change_adjustment(
            structural,
            previous_item,
        )
    )

    dynamic_adjustment = (
        price_adj
        + news_adj
        + volume_adj
        + risk_adj
        + structural_adj
    )

    dynamic_adjustment = clamp(
        dynamic_adjustment,
        -8.0,
        8.0,
    )

    opportunity_score = clamp(
        structural + dynamic_adjustment,
        0,
        100,
    )

    previous_opportunity = None

    if previous_item:
        previous_opportunity = safe_float(
            previous_item.get("opportunity_score"),
            opportunity_score,
        )

    opportunity_delta = (
        opportunity_score - previous_opportunity
        if previous_opportunity is not None
        else 0.0
    )

    drivers = [
        (abs(structural_adj), structural_reason),
        (abs(price_adj), price_reason),
        (abs(news_adj), news_reason),
        (abs(volume_adj), volume_reason),
        (abs(risk_adj), risk_reason),
    ]

    drivers.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    enriched = dict(stock)

    enriched.update(
        {
            "structural_score": round(structural, 1),
            "opportunity_score": round(opportunity_score, 1),
            "opportunity_delta": round(opportunity_delta, 1),
            "structural_delta": round(structural_delta, 1),
            "dynamic_adjustment": round(dynamic_adjustment, 1),
            "price_change": (
                round(price_change, 2)
                if price_change is not None
                else None
            ),
            "news_count": news_count,
            "opportunity_drivers": [
                reason
                for magnitude, reason in drivers
                if magnitude > 0
            ][:3],
        }
    )

    return enriched


def rank_daily_opportunities(
    scores: list[dict],
    movers: list[dict] | None = None,
    context: dict | None = None,
    *,
    record_memory: bool = True,
    memory_path: Path = DEFAULT_MEMORY_PATH,
) -> list[dict]:
    movers = movers or []
    context = context or {}

    move_lookup = mover_map(movers)
    news_counts = load_news_ticker_counts(context)

    memory = load_memory(memory_path)
    baseline = previous_baseline(
        memory,
        today_key(),
    )

    ranked = []

    for stock in scores or []:
        if not isinstance(stock, dict):
            continue

        symbol = clean_symbol(
            stock.get("ticker")
            or stock.get("symbol")
        )

        if not symbol:
            continue

        ranked.append(
            build_opportunity_item(
                stock=stock,
                mover=move_lookup.get(symbol),
                news_count=news_counts.get(symbol, 0),
                previous_item=baseline.get(symbol),
            )
        )

    ranked.sort(
        key=lambda item: (
            safe_float(item.get("opportunity_score")),
            safe_float(item.get("final_score")),
            safe_float(item.get("signal_overlap")),
        ),
        reverse=True,
    )

    if record_memory:
        save_memory(
            ranked,
            path=memory_path,
        )

    return ranked


def direction_text(delta: float) -> str:
    if delta > 0.05:
        return f"up {delta:+.1f}"

    if delta < -0.05:
        return f"down {delta:+.1f}"

    return "unchanged"


def build_top_opportunities_section(
    ranked: list[dict],
    limit: int = 3,
) -> str:
    if not ranked:
        return "No daily opportunities available."

    blocks = []

    for index, item in enumerate(ranked[:limit], 1):
        symbol = clean_symbol(
            item.get("ticker")
            or item.get("symbol")
        )

        opportunity = safe_float(
            item.get("opportunity_score")
        )

        structural = safe_float(
            item.get("structural_score")
        )

        delta = safe_float(
            item.get("opportunity_delta")
        )

        price = item.get("price_change")

        drivers = item.get("opportunity_drivers") or []

        driver_text = (
            "; ".join(str(value) for value in drivers[:2])
            if drivers
            else "structural conviction remains the main driver"
        )

        price_text = (
            f"{float(price):+.1f}%"
            if price is not None
            else "unavailable"
        )

        blocks.append(
            f"{index}. {symbol} - Opportunity {opportunity:.1f}/100 | "
            f"Structural {structural:.1f}/100 | {direction_text(delta)}\n"
            f"   Price: {price_text} | News signals: {int(item.get('news_count') or 0)}\n"
            f"   Why now: {driver_text}\n"
            f"   Risk: {item.get('risk_label') or 'Balanced'} | "
            f"Action: {item.get('action_label') or 'Watch Closely'}\n"
            f"   Full review: /tradeplan {symbol}"
        )

    return "\n\n".join(blocks)


def build_fastest_rising_section(
    ranked: list[dict],
    limit: int = 4,
) -> str:
    if not ranked:
        return "No opportunity-change data available."

    rising = sorted(
        ranked,
        key=lambda item: safe_float(
            item.get("opportunity_delta")
        ),
        reverse=True,
    )

    positive = [
        item
        for item in rising
        if safe_float(item.get("opportunity_delta")) > 0.05
    ]

    selected = positive[:limit]

    if not selected:
        return (
            "No meaningful positive opportunity-score changes "
            "versus the prior report."
        )

    lines = []

    for item in selected:
        symbol = clean_symbol(
            item.get("ticker")
            or item.get("symbol")
        )

        score = safe_float(
            item.get("opportunity_score")
        )

        delta = safe_float(
            item.get("opportunity_delta")
        )

        lines.append(
            f"- {symbol}: {score:.1f}/100 ({delta:+.1f})"
        )

    return "\n".join(lines)
