from telegram import Update
from telegram.ext import ContextTypes

from src.config.version_info import build_version_notes_text


async def versionnotes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(build_version_notes_text())