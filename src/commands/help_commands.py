from telegram import Update
from telegram.ext import ContextTypes

from src.config.command_catalog import (
    build_commands_menu_text,
    build_help_text,
)
from src.utils.telegram_messages import reply_long_message


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await reply_long_message(
        update=update,
        text=build_help_text(),
        title="🤖 Smart Money AI Help",
        parse_mode=None,
    )


async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await reply_long_message(
        update=update,
        text=build_commands_menu_text(),
        title="🤖 Smart Money AI Commands",
        parse_mode=None,
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    message = """
🛠️ Smart Money AI Admin

/deploycheck - Deployment health check
/securitycheck - Security check
/status - Bot status
/ping - Ping check
/diagnostics - Diagnostics
/version - Version
/versionnotes - Release notes
/backup - Backup
/logs - Logs
/restart - Restart bot
/quality - Report quality check

Research only. Not financial advice.
""".strip()

    await reply_long_message(
        update=update,
        text=message,
        title="🛠️ Smart Money AI Admin",
        parse_mode=None,
    )


# Compatibility aliases.
async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await help_command(update, context)


async def commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await commands_command(update, context)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_command(update, context)