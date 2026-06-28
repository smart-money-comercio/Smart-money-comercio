import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


PUBLIC_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("help", "Show help menu"),
    BotCommand("commands", "Show command list"),
    BotCommand("report", "Generate market report"),
    BotCommand("top10", "Show top ranked opportunities"),
    BotCommand("quote", "Get stock quote"),
    BotCommand("market", "Get market data"),
    BotCommand("ticker", "Quick ticker lookup"),
    BotCommand("scorecard", "Show stock scorecard"),
    BotCommand("risk", "Show risk profile"),
    BotCommand("earnings", "Show earnings data"),
    BotCommand("watchlist", "Manage watchlist"),
    BotCommand("defense", "Defense sector opportunities"),
    BotCommand("growth", "Growth stock opportunities"),
    BotCommand("dividends", "Dividend opportunities"),
    BotCommand("portfolio", "Portfolio summary"),
    BotCommand("congress", "Congressional trading signals"),
    BotCommand("insiders", "Insider trading signals"),
    BotCommand("smartmoney", "Smart money summary"),
    BotCommand("conviction", "High conviction opportunities"),
    BotCommand("undervalued", "Undervalued opportunities"),
    BotCommand("sec", "SEC filing summary"),
    BotCommand("filing", "Latest filing lookup"),
]


ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand("deploycheck", "Production health check"),
    BotCommand("status", "Bot status"),
    BotCommand("ping", "Bot ping test"),
    BotCommand("diagnostics", "Environment diagnostics"),
    BotCommand("health", "Health check"),
    BotCommand("system", "System info"),
    BotCommand("version", "Bot version"),
    BotCommand("senddaily", "Send daily report to channel"),
    BotCommand("testdaily", "Send daily report to this chat"),
    BotCommand("backup", "Create server backup"),
    BotCommand("logs", "Show recent service logs"),
    BotCommand("restart", "Restart production bot"),
    BotCommand("clearcache", "Clear loaded caches"),
    BotCommand("securitycheck", "Check server security status"),
    BotCommand("admin", "Show admin chat info"),
]


def parse_admin_chat_ids(raw_value: str | None) -> list[int | str]:
    if not raw_value:
        return []

    chat_ids: list[int | str] = []

    for item in raw_value.split(","):
        cleaned = item.strip()

        if not cleaned:
            continue

        if cleaned.startswith("@"):
            chat_ids.append(cleaned)
            continue

        try:
            chat_ids.append(int(cleaned))
        except ValueError:
            print(f"Skipping invalid admin chat ID: {cleaned}")

    return chat_ids


async def sync_commands() -> None:
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing from .env")

    admin_chat_ids = parse_admin_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_ID"))

    bot = Bot(token=BOT_TOKEN)

    print("Syncing public Telegram command menu...")
    await bot.set_my_commands(
        commands=PUBLIC_COMMANDS,
        scope=BotCommandScopeDefault(),
    )
    print(f"Public commands synced: {len(PUBLIC_COMMANDS)}")

    if not admin_chat_ids:
        print("No admin chat IDs found. Skipping admin command scope.")
        return

    for chat_id in admin_chat_ids:
        try:
            print(f"Syncing admin command menu for chat: {chat_id}")
            await bot.set_my_commands(
                commands=ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=chat_id),
            )
            print(f"Admin commands synced for {chat_id}: {len(ADMIN_COMMANDS)}")
        except Exception as exc:
            print(f"Failed to sync admin commands for {chat_id}: {exc}")

    print("Telegram command menu sync complete.")


if __name__ == "__main__":
    asyncio.run(sync_commands())