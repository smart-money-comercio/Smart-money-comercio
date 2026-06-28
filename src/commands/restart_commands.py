import subprocess

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import is_admin


SERVICE_NAME = "smart-money-ai-bot"
SYSTEMCTL_PATH = "/usr/bin/systemctl"


def trigger_restart() -> tuple[bool, str]:
    try:
        subprocess.Popen(
            [
                "sudo",
                "-n",
                SYSTEMCTL_PATH,
                "restart",
                SERVICE_NAME,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return True, "Restart command sent."

    except Exception as exc:
        return False, f"Restart failed: {exc}"


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized: admin only")
        return

    await update.message.reply_text(
        "🔄 Restarting Smart Money AI bot...\n\n"
        "You should receive the startup notification again shortly."
    )

    success, message = trigger_restart()

    if not success:
        await update.message.reply_text(f"❌ {message}")