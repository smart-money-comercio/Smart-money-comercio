import subprocess
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import is_admin


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = PROJECT_ROOT / "deployment" / "backup_server.sh"


def run_backup_script() -> tuple[bool, str]:
    if not BACKUP_SCRIPT.exists():
        return False, f"Backup script not found: {BACKUP_SCRIPT}"

    try:
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "/bin/bash",
                str(BACKUP_SCRIPT),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()

        combined_output = "\n".join(
            part for part in [output, error] if part
        ).strip()

        if result.returncode == 0:
            return True, combined_output or "Backup completed successfully."

        return False, combined_output or f"Backup failed with exit code {result.returncode}."

    except subprocess.TimeoutExpired:
        return False, "Backup timed out after 90 seconds."
    except Exception as exc:
        return False, f"Backup failed: {exc}"


def trim_output(text: str, max_length: int = 3000) -> str:
    if len(text) <= max_length:
        return text

    return text[-max_length:]


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized: admin only")
        return

    await update.message.reply_text("Creating Smart Money AI backup...")

    success, output = run_backup_script()
    trimmed_output = trim_output(output)

    if success:
        await update.message.reply_text(
            f"✅ Backup complete\n\n{trimmed_output}"
        )
        return

    await update.message.reply_text(
        f"❌ Backup failed\n\n{trimmed_output}"
    )