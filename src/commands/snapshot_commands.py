import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.intelligence.market_memory import build_what_changed_today
from src.reports.daily_report import (
    build_market_tone,
    collect_watchlist_movers,
    fetch_watchlist_quotes,
    format_percent,
    get_clean_headline_themes,
    get_macro_pressure,
    load_global_context,
)
from src.reports.top10_report import (
    classify_action_bucket,
    normalize_stock_items,
    rank_candidates,
)
from src.scoring.scoring_engine import get_stock_scores


def first_bullets(value: str, limit: int = 2) -> str:
    bullets = []

    for line in str(value or "").splitlines():
        cleaned = line.strip()

        if cleaned.startswith("•"):
            bullets.append(cleaned)

        if len(bullets) >= limit:
            break

    if bullets:
        return "\n".join(bullets)

    cleaned = " ".join(str(value or "").split())

    if cleaned:
        return f"• {cleaned[:220]}"

    return "• No major change signal available."


def format_score(score) -> str:
    try:
        return f"{float(score):.0f}/100"
    except Exception:
        return "N/A"


def build_top20_candidates(limit: int = 20) -> list[dict]:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    items = normalize_stock_items(raw_scores)
    return rank_candidates(items, limit=limit)


def get_top_idea(ranked: list[dict]) -> dict | None:
    if not ranked:
        return None

    return ranked[0]


def build_top_idea_line(top_idea: dict | None) -> str:
    if not top_idea:
        return "No top idea available."

    return (
        f"{top_idea.get('symbol', 'UNKNOWN')} — "
        f"{top_idea.get('conviction', 'Developing')} | "
        f"{format_score(top_idea.get('score'))}"
    )


def build_bucket_line(top_idea: dict | None) -> str:
    if not top_idea:
        return "Unavailable"

    try:
        return classify_action_bucket(top_idea)
    except Exception:
        return "Unavailable"


def build_theme_line(top_idea: dict | None, fallback_themes: list[str]) -> str:
    category = ""

    if top_idea:
        category = str(top_idea.get("category") or "").strip()

    if category and category.lower() not in {
        "unknown",
        "none",
        "n/a",
        "uncategorized",
    }:
        return category

    if fallback_themes:
        return ", ".join(fallback_themes[:3])

    return "No dominant theme detected."


def build_top_idea_action(top_idea: dict | None) -> str:
    if not top_idea:
        return "Use /top10 to review the current opportunity board."

    symbol = top_idea.get("symbol", "SYMBOL")
    bucket = build_bucket_line(top_idea)
    score = top_idea.get("score") or 0

    try:
        score = float(score)
    except Exception:
        score = 0

    if bucket == "Best Setup / Pullback Candidates":
        return f"Review /stock {symbol}; favor pullbacks or confirmation."

    if bucket == "Watch for Confirmation":
        return f"Review /stock {symbol}; wait for volume or catalyst confirmation."

    if bucket == "High Risk / Wait":
        return f"Review /risk {symbol}; elevated risk means patience first."

    if score >= 75:
        return f"Review /stock {symbol}; keep it high on watch."

    return "Use /top10 to review the broader opportunity board."


def build_mover_line(movers: list[dict]) -> str:
    if not movers:
        return "Live mover data unavailable."

    mover = movers[0]

    return (
        f"{mover['symbol']} is the largest live mover at "
        f"{format_percent(mover['change_percent'])}."
    )


def build_snapshot_actions(top_idea: dict | None, movers: list[dict]) -> str:
    actions = []

    if top_idea:
        symbol = top_idea.get("symbol", "").strip()

        if symbol:
            actions.append(f"/stock {symbol}")
            actions.append(f"/scorecard {symbol}")
    else:
        actions.append("/top10")

    if movers:
        actions.append(f"/stock {movers[0]['symbol']}")

    actions.append("/top10")
    actions.append("/calendar")

    deduped = []

    for action in actions:
        if action not in deduped:
            deduped.append(action)

    return "\n".join(f"• {action}" for action in deduped[:4])


def build_snapshot_report() -> str:
    ranked = build_top20_candidates(limit=20)
    top_idea = get_top_idea(ranked)

    global_context = load_global_context()
    global_context["scores"] = ranked

    watchlist_symbols, watchlist_quotes = fetch_watchlist_quotes(global_context)
    movers = collect_watchlist_movers(watchlist_symbols, watchlist_quotes)
    market_tone = build_market_tone(movers)

    themes = get_clean_headline_themes(global_context, limit=3)
    theme_text = build_theme_line(top_idea, themes)
    pressure = get_macro_pressure(global_context)

    what_changed_today = build_what_changed_today(
        context=global_context,
        top_scores=ranked[:1],
        movers=movers,
        market_tone=market_tone,
        watchlist_symbols=watchlist_symbols,
        record=False,
    )

    return f"""
📌 Smart Money AI Snapshot

Tone
{market_tone}

Top Idea
{build_top_idea_line(top_idea)}

Best Bucket
{build_bucket_line(top_idea)}

Top Theme
{theme_text}

Macro Pressure
{pressure}

Live Tape
{build_mover_line(movers)}

What Changed
{first_bullets(what_changed_today, limit=2)}

Action Read
{build_top_idea_action(top_idea)}

Next Actions
{build_snapshot_actions(top_idea, movers)}

Use /brief for the full daily read.
Research only. Not financial advice.
""".strip()


async def snapshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📌 Building smarter market snapshot..."
    )

    try:
        message = await asyncio.to_thread(build_snapshot_report)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money AI Snapshot\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )