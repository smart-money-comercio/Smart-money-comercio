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
    normalize_scores,
    translate_smart_money_label,
)
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_risk_label,
    get_ticker,
)


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


def build_top_watch_line(top_scores: list[dict]) -> str:
    if not top_scores:
        return "No top watch available."

    best = top_scores[0]
    ticker = get_ticker(best)
    label = translate_smart_money_label(best)
    risk = get_risk_label(best)
    action = get_action_label(best)

    return f"{ticker} — {label} | Risk: {risk} | Action: {action}"


def build_mover_line(movers: list[dict]) -> str:
    if not movers:
        return "Live mover data unavailable."

    mover = movers[0]

    return (
        f"{mover['symbol']} is the largest live mover at "
        f"{format_percent(mover['change_percent'])}."
    )


def build_snapshot_actions(top_scores: list[dict], movers: list[dict]) -> str:
    actions = []
    best = top_scores[0] if top_scores else None

    if best:
        ticker = get_ticker(best)
        actions.append(f"/scorecard {ticker}")
        actions.append(f"/volume {ticker}")
    else:
        actions.append("/top10")

    if movers:
        actions.append(f"/stock {movers[0]['symbol']}")

    actions.append("/calendar")

    return "\n".join(f"• {action}" for action in actions[:4])


def build_snapshot_report() -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_scores(raw_scores)
    top_scores = scores[:1]

    global_context = load_global_context()
    global_context["scores"] = scores

    watchlist_symbols, watchlist_quotes = fetch_watchlist_quotes(global_context)
    movers = collect_watchlist_movers(watchlist_symbols, watchlist_quotes)
    market_tone = build_market_tone(movers)

    themes = get_clean_headline_themes(global_context, limit=3)
    theme_text = ", ".join(themes) if themes else "No active theme detected."
    pressure = get_macro_pressure(global_context)

    what_changed_today = build_what_changed_today(
        context=global_context,
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        watchlist_symbols=watchlist_symbols,
        record=False,
    )

    return f"""
📌 Smart Money AI Snapshot

Tone
{market_tone}

Main Theme
{theme_text}

Macro Pressure
{pressure}

Top Watch
{build_top_watch_line(top_scores)}

Live Tape
{build_mover_line(movers)}

What Changed
{first_bullets(what_changed_today, limit=2)}

Next Actions
{build_snapshot_actions(top_scores, movers)}

Use /brief for the full daily read.
Research only. Not financial advice.
""".strip()


async def snapshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📌 Building market snapshot..."
    )

    try:
        message = await asyncio.to_thread(build_snapshot_report)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money AI Snapshot\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}"
        )