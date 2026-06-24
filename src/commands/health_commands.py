import os
import time

import yfinance as yf
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ContextTypes

from src.utils.cache import get_cache, set_cache

load_dotenv()


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    checks = []

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    openai_key = os.getenv("OPENAI_API_KEY")
    sec_user_agent = os.getenv("SEC_USER_AGENT")

    checks.append(("Telegram token", bool(bot_token)))
    checks.append(("OpenAI key", bool(openai_key)))
    checks.append(("SEC user agent", bool(sec_user_agent)))

    try:
        set_cache("health:test", "ok", ttl_seconds=60)
        cache_ok = get_cache("health:test") == "ok"
    except Exception:
        cache_ok = False

    checks.append(("Cache system", cache_ok))

    start_time = time.time()

    try:
        spy = yf.Ticker("SPY")
        history = spy.history(period="5d")
        market_ok = not history.empty
    except Exception:
        market_ok = False

    checks.append(("Market data", market_ok))

    elapsed = round(time.time() - start_time, 2)

    passed = sum(1 for _, status in checks if status)
    total = len(checks)

    lines = [
        "🩺 Smart Money AI Health Check",
        "",
        f"Status: {passed}/{total} checks passed",
        f"Market data response time: {elapsed}s",
        "",
    ]

    for name, status in checks:
        icon = "✅" if status else "❌"
        lines.append(f"{icon} {name}")

    lines.extend(
        [
            "",
            "Core commands to test:",
            "/quote PLTR",
            "/earnings PLTR",
            "/scorecard PLTR",
            "/undervalued",
        ]
    )

    await update.message.reply_text("\n".join(lines))