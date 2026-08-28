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


def compact_sentence(value: str, max_chars: int = 260) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def human_list(items: list[str], limit: int = 4, fallback: str = "none") -> str:
    cleaned = unique_values(
        [str(item or "").strip() for item in items if str(item or "").strip()],
        limit=limit,
    )

    if not cleaned:
        return fallback

    if len(cleaned) == 1:
        return cleaned[0]

    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"

    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def find_context_block(
    blocks: list[IntelligenceContextBlock],
    feature_name: str,
) -> IntelligenceContextBlock | None:
    target = str(feature_name or "").strip().lower()

    for block in blocks:
        if str(block.feature or "").strip().lower() == target:
            return block

    return None


def infer_daily_posture(themes: list[str], risks: list[str]) -> str:
    combined = " ".join(themes + risks).lower()

    if "risk-off" in combined:
        return "defensive"

    if "cautious" in combined:
        return "cautious and selective"

    if "rates" in combined or "treasury" in combined or "yields" in combined:
        return "rate-sensitive"

    if "china" in combined or "trade" in combined:
        return "macro-sensitive"

    if "ai" in combined or "semiconductor" in combined:
        return "constructive but selective"

    return "balanced"


def build_alert_phrase(alert_block: IntelligenceContextBlock | None) -> str:
    if not alert_block:
        return "the alert queue has not been refreshed yet"

    critical_count = alert_block.metadata.get("critical_count", 0)
    warning_count = alert_block.metadata.get("warning_count", 0)

    try:
        critical_count = int(critical_count or 0)
        warning_count = int(warning_count or 0)
    except Exception:
        critical_count = 0
        warning_count = 0

    if critical_count == 0 and warning_count == 0:
        return "the alert queue is quiet"

    if critical_count > 0:
        return f"the alert queue shows {critical_count} critical and {warning_count} warning signals"

    return f"the alert queue shows {warning_count} warning signals"


def build_professional_signal(
    blocks: list[IntelligenceContextBlock],
    summary: dict,
) -> str:
    alert_block = find_context_block(blocks, "Alert Monitor")
    news_block = find_context_block(blocks, "News Intelligence")

    themes = summary.get("themes", [])
    risks = summary.get("risks", [])

    posture = infer_daily_posture(themes, risks)
    theme_text = human_list(themes, limit=3, fallback="the broader market tape")
    alert_phrase = build_alert_phrase(alert_block)

    if news_block:
        return compact_sentence(
            f"The daily read is {posture}. {theme_text} are driving the market context, while {alert_phrase}.",
            max_chars=260,
        )

    return compact_sentence(
        f"The daily read is {posture}. {alert_phrase}, so the focus should stay on confirmed setups rather than broad risk-taking.",
        max_chars=260,
    )


def build_professional_implication(summary: dict) -> str:
    symbols = summary.get("symbols", [])
    themes = summary.get("themes", [])

    symbol_text = human_list(symbols, limit=5, fallback="")
    theme_text = human_list(themes, limit=3, fallback="the current macro setup")

    if symbol_text:
        return compact_sentence(
            f"Focus first on {symbol_text}. Treat headlines, alert signals, and external ratings as confirmation inputs, not stand-alone buy signals.",
            max_chars=330,
        )

    return compact_sentence(
        f"Stay selective and let {theme_text} guide positioning. Prioritize quality setups with confirmed price action, volume, and risk control.",
        max_chars=330,
    )


def build_professional_validation(summary: dict) -> str:
    commands = summary.get("commands", [])

    preferred_commands = [
        "/alerts",
        "/newsintel",
        "/stock",
        "/risk",
        "/volume",
        "/stockdata",
    ]

    available = []

    command_text = " ".join(commands)

    for command in preferred_commands:
        if command in command_text or command in preferred_commands:
            available.append(command)

    command_list = human_list(available, limit=6, fallback="/alerts, /newsintel, /stock, /risk, /volume, and /stockdata")

    return compact_sentence(
        f"Before acting, confirm the setup with {command_list}. Upgrade conviction only when the score, news context, volume, risk, and external validation agree.",
        max_chars=330,
    )


def build_integrated_summary_from_blocks(blocks: list[IntelligenceContextBlock]) -> str:
    if not blocks:
        return (
            "Signal: No integrated intelligence memory is available yet.\n"
            "Implication: Run news and alert scans before relying on the daily read.\n"
            "Validation: Use /newsintel refresh, /alerts refresh, and /stock SYMBOL."
        )

    summary = summarize_blocks(blocks)

    signal_text = build_professional_signal(blocks, summary)
    implication_text = build_professional_implication(summary)
    validation_text = build_professional_validation(summary)

    return (
        f"Signal: {signal_text}\n"
        f"Implication: {implication_text}\n"
        f"Validation: {validation_text}"
    )