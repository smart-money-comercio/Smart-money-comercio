from src.intelligence.daily_ai_summary_context import build_integrated_daily_ai_summary
from src.intelligence.intelligence_context_registry import (
    IntelligenceContextBlock,
    collect_intelligence_context,
)

# Import registers providers.
import src.intelligence.intelligence_context_providers  # noqa: F401


def compact_text(value, max_chars: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def comma_list(items, fallback: str = "None", limit: int = 8) -> str:
    cleaned = []

    for item in items or []:
        text = str(item or "").strip()

        if text and text not in cleaned:
            cleaned.append(text)

        if len(cleaned) >= limit:
            break

    if not cleaned:
        return fallback

    return ", ".join(cleaned)


def provider_health(block: IntelligenceContextBlock) -> str:
    if not block.signal and not block.implication and not block.validation:
        return "Weak"

    if block.feature in {"Alert Monitor", "News Intelligence"} and not block.symbols and not block.themes:
        return "Limited"

    return "Healthy"


def format_provider_block(block: IntelligenceContextBlock, index: int) -> str:
    return f"""
{index}. {block.feature}
Status: {provider_health(block)}
Priority: {block.priority}
Signal: {compact_text(block.signal, 170)}
Themes: {comma_list(block.themes, limit=6)}
Symbols: {comma_list(block.symbols, limit=8)}
Risks: {comma_list(block.risks, limit=5)}
Commands: {comma_list(block.commands, limit=6)}
""".strip()


def build_contextstatus_report() -> str:
    blocks = collect_intelligence_context()

    if not blocks:
        return """
🧠 Context Status

Status: No intelligence providers are currently feeding the Smart Money Summary.

What to run:
/newsintel refresh
/alerts refresh
/stockdata NVDA refresh

Then run:
/summarypreview
/contextstatus

Research only. Not financial advice.
""".strip()

    healthy = len([block for block in blocks if provider_health(block) == "Healthy"])
    limited = len([block for block in blocks if provider_health(block) == "Limited"])
    weak = len([block for block in blocks if provider_health(block) == "Weak"])

    provider_blocks = "\n\n".join(
        format_provider_block(block, index)
        for index, block in enumerate(blocks, start=1)
    )

    features = comma_list([block.feature for block in blocks], limit=12)

    symbols = []
    themes = []
    risks = []

    for block in blocks:
        symbols.extend(block.symbols)
        themes.extend(block.themes)
        risks.extend(block.risks)

    return f"""
🧠 Smart Money Context Status

Summary
Providers Loaded: {len(blocks)}
Healthy: {healthy}
Limited: {limited}
Weak: {weak}
Features: {features}

Current Context
Themes: {comma_list(themes, limit=10)}
Symbols: {comma_list(symbols, limit=10)}
Risks: {comma_list(risks, limit=8)}

Provider Detail
{provider_blocks}

How to refresh the brain
• /newsintel refresh — refresh news memory
• /alerts refresh — refresh alert memory
• /stockdata SYMBOL refresh — refresh StockAnalysis cache
• /summarypreview — preview the Smart Money Summary

Research only. Not financial advice.
""".strip()


def build_summarypreview_report() -> str:
    summary = build_integrated_daily_ai_summary()

    return f"""
🧠 Smart Money Summary Preview

{summary}

Provider Status
Use /contextstatus to see which intelligence providers are feeding this summary.

Research only. Not financial advice.
""".strip()