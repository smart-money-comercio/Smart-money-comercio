import subprocess
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import is_admin


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECURITY_SCRIPT = PROJECT_ROOT / "deployment" / "security_check.sh"


def trim_output(text: str, max_length: int = 3500) -> str:
    if len(text) <= max_length:
        return text

    return text[-max_length:]


def run_security_check() -> tuple[bool, str]:
    if not SECURITY_SCRIPT.exists():
        return False, f"Security check script not found: {SECURITY_SCRIPT}"

    try:
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "/bin/bash",
                str(SECURITY_SCRIPT),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()

        combined_output = "\n".join(
            part for part in [output, error] if part
        ).strip()

        if result.returncode == 0:
            return True, combined_output or "Security check completed."

        return False, combined_output or f"Security check failed with exit code {result.returncode}."

    except subprocess.TimeoutExpired:
        return False, "Security check timed out after 30 seconds."
    except Exception as exc:
        return False, f"Security check failed: {exc}"


async def securitycheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized: admin only")
        return

    await update.message.reply_text("Running Smart Money AI security check...")

    success, output = run_security_check()
    output = trim_output(output)

    if success:
        await update.message.reply_text(output)
        return

    await update.message.reply_text(f"❌ Security check failed\n\n{output}")