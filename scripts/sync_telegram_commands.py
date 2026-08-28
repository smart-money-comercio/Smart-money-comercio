import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


load_dotenv(PROJECT_ROOT / ".env")


from src.config.command_catalog import (  # noqa: E402
    ADMIN_COMMANDS,
    CORE_COMMANDS,
    DAILY_REPORT_COMMANDS,
    MARKET_CONTEXT_COMMANDS,
    SMART_MONEY_COMMANDS,
    STOCK_RESEARCH_COMMANDS,
    THEME_COMMANDS,
    WATCHLIST_COMMANDS,
)


MAX_COMMANDS = 100


def clean_command(command_text: str) -> str:
    command = str(command_text or "").strip().split()[0]
    command = command.replace("/", "").strip().lower()
    command = re.sub(r"[^a-z0-9_]", "", command)
    return command[:32]


def clean_description(description: str) -> str:
    text = str(description or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:256]


def collect_commands() -> list[BotCommand]:
    groups = [
        CORE_COMMANDS,
        DAILY_REPORT_COMMANDS,
        STOCK_RESEARCH_COMMANDS,
        WATCHLIST_COMMANDS,
        THEME_COMMANDS,
        MARKET_CONTEXT_COMMANDS,
        SMART_MONEY_COMMANDS,
        ADMIN_COMMANDS,
    ]

    commands = []
    seen = set()

    for group in groups:
        for command_text, description in group:
            command = clean_command(command_text)

            if not command or command in seen:
                continue

            seen.add(command)
            commands.append(
                BotCommand(
                    command=command,
                    description=clean_description(description),
                )
            )

    return commands[:MAX_COMMANDS]


async def show_scope(bot: Bot, scope, label: str) -> None:
    commands = await bot.get_my_commands(scope=scope)
    names = [f"/{command.command}" for command in commands]

    print("")
    print(f"{label}: {len(commands)} commands")
    for target in ["/newsintel", "/newsmemory", "/alerts", "/dailyalerts", "/alertstatus", "/macronews", "/tickernews"]:
        print(f"  {target}: {'FOUND' if target in names else 'MISSING'}")


async def main() -> int:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()

    if not token:
        print("Telegram command sync failed.")
        print("Missing TELEGRAM_BOT_TOKEN or BOT_TOKEN in .env")
        return 1

    commands = collect_commands()

    bot = Bot(token=token)
    me = await bot.get_me()

    scopes = [
        ("Default", BotCommandScopeDefault()),
        ("All private chats", BotCommandScopeAllPrivateChats()),
        ("All group chats", BotCommandScopeAllGroupChats()),
        ("All chat administrators", BotCommandScopeAllChatAdministrators()),
    ]

    print("Telegram command dropdown sync")
    print(f"Bot: @{me.username}")
    print(f"Commands Prepared: {len(commands)}")

    for label, scope in scopes:
        await bot.delete_my_commands(scope=scope)
        await bot.set_my_commands(commands, scope=scope)
        print(f"Synced scope: {label}")

    print("")
    print("Status: PASS")
    print(f"Commands Synced Per Scope: {len(commands)}")

    for label, scope in scopes:
        await show_scope(bot, scope, label)

    print("")
    print("Synced command names:")
    for command in commands:
        print(f"/{command.command} - {command.description}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))