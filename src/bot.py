import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder
from src.commands.register_commands import register_commands

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing from .env")

    print("Starting Smart Money AI bot...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    register_commands(app)

    print("Smart Money AI bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()