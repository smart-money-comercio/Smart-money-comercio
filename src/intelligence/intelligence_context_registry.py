from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class IntelligenceContextBlock:
    feature: str
    priority: int = 50
    signal: str = ""
    implication: str = ""
    validation: str = ""
    themes: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


ContextProvider = Callable[[], IntelligenceContextBlock | None]


_CONTEXT_PROVIDERS: list[ContextProvider] = []


def register_context_provider(provider: ContextProvider) -> None:
    if provider not in _CONTEXT_PROVIDERS:
        _CONTEXT_PROVIDERS.append(provider)


def clear_context_providers() -> None:
    _CONTEXT_PROVIDERS.clear()


def get_registered_context_providers() -> list[ContextProvider]:
    return list(_CONTEXT_PROVIDERS)


def collect_intelligence_context() -> list[IntelligenceContextBlock]:
    blocks: list[IntelligenceContextBlock] = []

    for provider in get_registered_context_providers():
        try:
            block = provider()

            if block:
                blocks.append(block)

        except Exception:
            continue

    blocks.sort(key=lambda item: item.priority, reverse=True)
    return blocks


def unique_values(values: list[str], limit: int = 10) -> list[str]:
    cleaned = []
    seen = set()

    for value in values:
        item = str(value or "").strip()

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(key)
        cleaned.append(item)

        if len(cleaned) >= limit:
            break

    return cleaned


def summarize_blocks(blocks: list[IntelligenceContextBlock]) -> dict:
    signals = unique_values(
        [block.signal for block in blocks if block.signal],
        limit=8,
    )

    implications = unique_values(
        [block.implication for block in blocks if block.implication],
        limit=8,
    )

    validations = unique_values(
        [block.validation for block in blocks if block.validation],
        limit=8,
    )

    themes = unique_values(
        [theme for block in blocks for theme in block.themes],
        limit=12,
    )

    symbols = unique_values(
        [symbol for block in blocks for symbol in block.symbols],
        limit=12,
    )

    risks = unique_values(
        [risk for block in blocks for risk in block.risks],
        limit=12,
    )

    commands = unique_values(
        [command for block in blocks for command in block.commands],
        limit=12,
    )

    features = unique_values(
        [block.feature for block in blocks if block.feature],
        limit=20,
    )

    return {
        "signals": signals,
        "implications": implications,
        "validations": validations,
        "themes": themes,
        "symbols": symbols,
        "risks": risks,
        "commands": commands,
        "features": features,
    }


def format_bullets(items: list[str], fallback: str = "No signal available.") -> str:
    if not items:
        return f"• {fallback}"

    return "\n".join(f"• {item}" for item in items)


def comma_list(items: list[str], fallback: str = "None") -> str:
    if not items:
        return fallback

    return ", ".join(items)


def build_integrated_summary_from_blocks(blocks: list[IntelligenceContextBlock]) -> str:
    if not blocks:
        return """
Signal:
No integrated intelligence memory is available yet.

Implication:
Run /newsintel, /alerts, and relevant ticker commands to build the daily context.

Validation:
Use /newsintel refresh, /alerts refresh, /stock SYMBOL, /tickernews SYMBOL, and /stockdata SYMBOL.
""".strip()

    summary = summarize_blocks(blocks)

    return f"""
Signal:
{format_bullets(summary["signals"], "No dominant integrated signal detected.")}

Implication:
{format_bullets(summary["implications"], "No major integrated implication detected.")}

Validation:
{format_bullets(summary["validations"], "No validation path detected.")}

Context Stack:
• Features: {comma_list(summary["features"])}
• Themes: {comma_list(summary["themes"])}
• Symbols: {comma_list(summary["symbols"])}
• Risks: {comma_list(summary["risks"])}

Suggested Commands:
{format_bullets(summary["commands"], "/newsintel\n• /alerts\n• /portfolio")}
""".strip()