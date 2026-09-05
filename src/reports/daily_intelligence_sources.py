from src.intelligence.intelligence_context_registry import collect_intelligence_context

# Import registers current providers.
import src.intelligence.intelligence_context_providers  # noqa: F401


EXPECTED_PROVIDER_LABELS = {
    "Alert Monitor": "Alert Monitor",
    "News Intelligence": "News Intelligence",
    "StockAnalysis Cache": "StockAnalysis",
    "Alert Settings": "Alert Settings",
}


def provider_status_map() -> dict[str, bool]:
    try:
        blocks = collect_intelligence_context()
    except Exception:
        blocks = []

    loaded_features = {str(block.feature or "").strip() for block in blocks}

    return {
        friendly_name: provider_name in loaded_features
        for provider_name, friendly_name in EXPECTED_PROVIDER_LABELS.items()
    }


def status_label(active: bool) -> str:
    return "active" if active else "not loaded yet"


def build_daily_intelligence_stack_line() -> str:
    return (
        "Smart Money Summary, Trade Plan Snapshot, News Intelligence, Alert Monitor, "
        "StockAnalysis, Alert Settings, Watchlist Evolution, and Market Memory are feeding today's report."
    )


def build_daily_intelligence_sources_section() -> str:
    providers = provider_status_map()

    news = status_label(providers.get("News Intelligence", False))
    alerts = status_label(providers.get("Alert Monitor", False))
    stockanalysis = status_label(providers.get("StockAnalysis", False))
    settings = status_label(providers.get("Alert Settings", False))

    return (
        "Intelligence Used Today\n"
        f"? Active stack: Smart Money Summary, Trade Plan Snapshot, News Intelligence ({news}), "
        f"Alert Monitor ({alerts}), StockAnalysis ({stockanalysis}), Alert Settings ({settings}), "
        "Watchlist Evolution, and Market Memory."
    )
