import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from dotenv import load_dotenv
from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

try:
    from telegram import BotCommandScopeChat
except Exception:
    BotCommandScopeChat = None


from src.config.command_catalog import get_all_commands


LANGUAGE_CODES = [None, "en", "es"]


def get_token() -> str:
    load_dotenv(PROJECT_ROOT / ".env")

    token = (
        os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("BOT_TOKEN")
        or ""
    ).strip()

    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or BOT_TOKEN in .env")

    return token


def clean_description(description: str) -> str:
    text = " ".join(str(description or "").split())

    if not text:
        return "Smart Money AI command"

    if len(text) > 256:
        return text[:253].rstrip() + "..."

    return text


def build_bot_commands() -> list[BotCommand]:
    commands: list[BotCommand] = []
    seen: set[str] = set()

    for raw_command, raw_description in get_all_commands():
        command_name = str(raw_command or "").strip().split()[0].lstrip("/").lower()

        if not command_name:
            continue

        if command_name in seen:
            continue

        seen.add(command_name)

        commands.append(
            BotCommand(
                command=command_name,
                description=clean_description(raw_description),
            )
        )

    if len(commands) > 100:
        raise RuntimeError(f"Telegram allows at most 100 bot commands. Prepared: {len(commands)}")

    return commands


def base_scopes():
    return [
        ("Default", BotCommandScopeDefault()),
        ("All private chats", BotCommandScopeAllPrivateChats()),
        ("All group chats", BotCommandScopeAllGroupChats()),
        ("All chat administrators", BotCommandScopeAllChatAdministrators()),
    ]


def chat_scopes_from_env():
    raw_chat_ids = (
        os.getenv("TELEGRAM_COMMAND_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or ""
    ).strip()

    if not raw_chat_ids or BotCommandScopeChat is None:
        return []

    scopes = []

    for raw_chat_id in raw_chat_ids.split(","):
        chat_id = raw_chat_id.strip()

        if not chat_id:
            continue

        scopes.append((f"Exact chat {chat_id}", BotCommandScopeChat(chat_id=chat_id)))

    return scopes


async def reset_scope(bot: Bot, scope_name: str, scope, commands: list[BotCommand], language_code):
    label = language_code or "default"

    await bot.delete_my_commands(scope=scope, language_code=language_code)
    await bot.set_my_commands(commands=commands, scope=scope, language_code=language_code)

    current = await bot.get_my_commands(scope=scope, language_code=language_code)
    current_names = {command.command for command in current}

    context_found = "contextstatus" in current_names
    preview_found = "summarypreview" in current_names

    print(f"Synced scope: {scope_name} | language: {label} | commands: {len(current)}")
    print(f"  /contextstatus: {'FOUND' if context_found else 'MISSING'}")
    print(f"  /summarypreview: {'FOUND' if preview_found else 'MISSING'}")

    return context_found and preview_found and len(current) == len(commands)


async def set_menu_button(bot: Bot):
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        print("Default menu button set to commands.")
    except Exception as error:
        print(f"Menu button update skipped: {type(error).__name__}: {error}")


async def main() -> int:
    token = get_token()
    commands = build_bot_commands()
    bot = Bot(token=token)

    me = await bot.get_me()

    print("Telegram command dropdown sync")
    print(f"Bot: @{me.username}")
    print(f"Commands Prepared: {len(commands)}")
    print("Languages: default, en, es")
    print("")

    await set_menu_button(bot)

    all_ok = True
    scopes = base_scopes() + chat_scopes_from_env()

    for scope_name, scope in scopes:
        for language_code in LANGUAGE_CODES:
            ok = await reset_scope(
                bot=bot,
                scope_name=scope_name,
                scope=scope,
                commands=commands,
                language_code=language_code,
            )
            all_ok = all_ok and ok

    print("")
    print(f"Status: {'PASS' if all_ok else 'FAIL'}")
    print(f"Commands Synced Per Scope: {len(commands)}")
    print("")

    print("Synced command names:")
    for command in commands:
        print(f"/{command.command} - {command.description}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))