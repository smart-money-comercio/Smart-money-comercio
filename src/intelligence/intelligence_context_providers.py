import json
import os
import re
from pathlib import Path
from typing import Any

from src.intelligence.intelligence_context_registry import (
    IntelligenceContextBlock,
    register_context_provider,
)


STOCKANALYSIS_CACHE_FILE = Path(os.getenv("STOCKANALYSIS_CACHE_FILE", "data/stockanalysis_cache.json"))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def clean_symbol(value: Any) -> str:
    return str(value or "").upper().replace("$", "").strip()


def unique_symbols(items: list[Any], limit: int = 12) -> list[str]:
    symbols = []
    seen = set()

    for item in items:
        symbol = clean_symbol(item)

        if not symbol:
            continue

        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", symbol):
            continue

        if symbol in seen:
            continue

        seen.add(symbol)
        symbols.append(symbol)

        if len(symbols) >= limit:
            break

    return symbols


def latest_memory_record(loader) -> dict:
    try:
        memory = loader()
    except Exception:
        return {}

    records = memory.get("records", [])

    if isinstance(records, list) and records:
        latest = records[-1]

        if isinstance(latest, dict):
            return latest

    return {}


def alert_context_provider() -> IntelligenceContextBlock | None:
    try:
        from src.intelligence.alert_evolution import load_alert_memory
    except Exception:
        return None

    latest = latest_memory_record(load_alert_memory)

    if not latest:
        return None

    symbols = []

    for key in [
        "highest_priority_symbols",
        "new_priority_symbols",
        "deteriorating_symbols",
        "validation_symbols",
        "risk_symbols",
    ]:
        value = latest.get(key, [])

        if isinstance(value, list):
            symbols.extend(value)

    alert_regime = str(latest.get("alert_regime", "unknown"))
    macro_regime = str(latest.get("macro_regime", "unknown"))
    risk_regime = str(latest.get("risk_regime", "unknown"))
    critical_count = safe_int(latest.get("critical_count", 0))
    warning_count = safe_int(latest.get("warning_count", 0))

    return IntelligenceContextBlock(
        feature="Alert Monitor",
        priority=100,
        signal=f"Alert regime: {alert_regime}. Critical alerts: {critical_count}; warnings: {warning_count}.",
        implication=f"Alert posture is tied to {macro_regime} and {risk_regime}. Prioritize names appearing in alert queues before adding new risk.",
        validation="Validate alert names with /stock, /scorecard, /risk, /volume, /tickernews, and /stockdata.",
        themes=[macro_regime, risk_regime],
        symbols=unique_symbols(symbols),
        risks=[risk_regime],
        commands=["/alerts", "/dailyalerts", "/alertstatus"],
        metadata={
            "critical_count": critical_count,
            "warning_count": warning_count,
        },
    )


def news_context_provider() -> IntelligenceContextBlock | None:
    try:
        from src.intelligence.news_evolution import load_news_memory
    except Exception:
        return None

    latest = latest_memory_record(load_news_memory)

    if not latest:
        return None

    news_regime = str(latest.get("news_regime", "unknown"))
    risk_regime = str(latest.get("risk_regime", "unknown"))
    portfolio_impact = str(latest.get("portfolio_impact", "unknown"))

    themes = latest.get("top_themes", [])
    tickers = latest.get("top_tickers", [])

    if not isinstance(themes, list):
        themes = []

    if not isinstance(tickers, list):
        tickers = []

    return IntelligenceContextBlock(
        feature="News Intelligence",
        priority=95,
        signal=f"News regime: {news_regime}. Risk read: {risk_regime}.",
        implication=portfolio_impact,
        validation="Validate news-driven themes with /newsintel, /macronews, /tickernews SYMBOL, /stock SYMBOL, and /alerts.",
        themes=[str(theme) for theme in themes[:10]],
        symbols=unique_symbols(tickers),
        risks=[risk_regime],
        commands=["/newsintel", "/newsmemory", "/macronews", "/tickernews SYMBOL"],
        metadata={
            "headline_count": latest.get("headline_count", 0),
        },
    )


def collect_stockanalysis_symbols_from_cache() -> list[str]:
    try:
        if not STOCKANALYSIS_CACHE_FILE.exists():
            return []

        raw = STOCKANALYSIS_CACHE_FILE.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    symbols = set()

    for match in re.findall(r"/stocks/([a-zA-Z][a-zA-Z0-9.\-]{0,7})/", raw):
        symbols.add(match.upper())

    for match in re.findall(r'"symbol"\s*:\s*"([A-Za-z][A-Za-z0-9.\-]{0,7})"', raw):
        symbols.add(match.upper())

    for match in re.findall(r'"ticker"\s*:\s*"([A-Za-z][A-Za-z0-9.\-]{0,7})"', raw):
        symbols.add(match.upper())

    for match in re.findall(r'"([A-Z]{1,6})"\s*:\s*\{', raw):
        symbols.add(match.upper())

    return unique_symbols(sorted(symbols), limit=12)


def stockanalysis_context_provider() -> IntelligenceContextBlock | None:
    symbols = collect_stockanalysis_symbols_from_cache()

    if not symbols:
        return None

    return IntelligenceContextBlock(
        feature="StockAnalysis Cache",
        priority=80,
        signal=f"External StockAnalysis data is cached for {', '.join(symbols[:6])}.",
        implication="Use StockAnalysis as external analyst/fundamental validation, not as the sole action source.",
        validation="Cross-check cached StockAnalysis names with /stockdata, /analyst, /stock, /risk, and /volume.",
        themes=["External analyst consensus", "Fundamentals", "Valuation"],
        symbols=symbols,
        risks=["External consensus can lag price action and Smart Money signal changes."],
        commands=["/stockdata SYMBOL", "/analyst SYMBOL", "/stock SYMBOL"],
        metadata={
            "cached_symbol_count": len(symbols),
        },
    )


def alert_settings_context_provider() -> IntelligenceContextBlock | None:
    try:
        from src.config.alert_presets import detect_current_preset
        from src.config.alert_rules import get_alert_rules
    except Exception:
        return None

    try:
        preset = detect_current_preset()
        rules = get_alert_rules()
    except Exception:
        return None

    return IntelligenceContextBlock(
        feature="Alert Settings",
        priority=60,
        signal=f"Alert preset mode: {preset}. Priority threshold: {rules.get('priority_score', 'unknown')}.",
        implication="Daily alert sensitivity is governed by the active preset and environment thresholds.",
        validation="Use /alertsettings and /alertrules before interpreting alert count changes as market changes.",
        themes=["Alert configuration", "Monitoring sensitivity"],
        symbols=[],
        risks=["Threshold changes can alter alert volume without a true market-regime change."],
        commands=["/alertsettings", "/alertrules", "/alertpreset MODE"],
        metadata={
            "preset": preset,
            "priority_score": rules.get("priority_score"),
            "strong_priority_score": rules.get("strong_priority_score"),
        },
    )


def register_default_context_providers() -> None:
    register_context_provider(alert_context_provider)
    register_context_provider(news_context_provider)
    register_context_provider(stockanalysis_context_provider)
    register_context_provider(alert_settings_context_provider)


# Side-effect registration for daily summary imports.
register_default_context_providers()