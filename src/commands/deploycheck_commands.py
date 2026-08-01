import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.utils.deploy_health import build_deploy_health_report


async def deploycheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🚀 Checking deployment health..."
    )

    try:
        message = await asyncio.to_thread(build_deploy_health_report)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Deploy Health\n"
            "Status: CHECK\n\n"
            f"Error: {type(error).__name__}: {error}"
        )