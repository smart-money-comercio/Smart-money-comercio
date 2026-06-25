import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ContextTypes

from src.utils.cache import clear_cache

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)


def clean_id(value):
    if value is None:
        return ""

    return str(value).strip().strip('"').strip("'")


def get_admin_chat_ids():
    raw_value = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    if not raw_value:
        return []

    return [
        clean_id(item)
        for item in raw_value.split(",")
        if clean_id(item)
    ]


def is_admin_chat(chat_id):
    current_chat_id = clean_id(chat_id)
    allowed_ids = get_admin_chat_ids()

    return current_chat_id in allowed_ids


async def clearcache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = clean_id(update.effective_chat.id)
    allowed_ids = get_admin_chat_ids()

    if not is_admin_chat(chat_id):
        await update.message.reply_text(
            "Unauthorized: admin only.\n\n"
            f"Current Telegram chat ID:\n{chat_id}\n\n"
            f"Admin IDs loaded from .env:\n{allowed_ids}\n\n"
            "To authorize this chat, add this exact line to your .env file:\n"
            f"TELEGRAM_CHAT_ID={chat_id}"
        )
        return

    cache_type = context.args[0].lower() if context.args else "all"

    if cache_type == "market":
        clear_cache("market:")
        message = "✅ Market data cache cleared."

    elif cache_type == "earnings":
        clear_cache("earnings:")
        message = "✅ Earnings data cache cleared."

    elif cache_type == "health":
        clear_cache("health:")
        message = "✅ Health check cache cleared."

    elif cache_type == "all":
        clear_cache()
        message = "✅ All cache cleared."

    else:
        message = (
            "Unknown cache type.\n\n"
            "Use one of these:\n"
            "/clearcache\n"
            "/clearcache all\n"
            "/clearcache market\n"
            "/clearcache earnings\n"
            "/clearcache health"
        )

    await update.message.reply_text(message)