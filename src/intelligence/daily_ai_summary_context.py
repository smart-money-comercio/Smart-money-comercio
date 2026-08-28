from src.intelligence.intelligence_context_registry import (
    build_integrated_summary_from_blocks,
    collect_intelligence_context,
)

# Import registers current and future providers.
import src.intelligence.intelligence_context_providers  # noqa: F401


def build_integrated_daily_ai_summary(base_summary: str = "") -> str:
    blocks = collect_intelligence_context()

    if not blocks and base_summary:
        return base_summary.strip()

    return build_integrated_summary_from_blocks(blocks)