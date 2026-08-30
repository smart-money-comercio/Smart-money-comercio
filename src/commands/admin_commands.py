import os
import sys
import time
import platform
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes


BOT_START_TIME = datetime.now()


def get_admin_chat_ids() -> set[str]:
    raw_ids = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

    return {
        chat_id.strip()
        for chat_id in raw_ids.split(",")
        if chat_id.strip()
    }


def get_command_chat_ids() -> set[str]:
    raw_ids = (
        os.getenv("TELEGRAM_COMMAND_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or ""
    )

    return {
        chat_id.strip()
        for chat_id in raw_ids.split(",")
        if chat_id.strip()
    }


def get_current_chat_id(update: Update) -> str:
    if update.effective_chat:
        return str(update.effective_chat.id)

    return "UNKNOWN"


def is_admin(update: Update) -> bool:
    current_chat_id = get_current_chat_id(update)
    admin_chat_ids = get_admin_chat_ids()

    return current_chat_id in admin_chat_ids


def env_loaded(env_name: str) -> str:
    value = os.getenv(env_name)
    return "Loaded" if value else "Missing"


def env_loaded_bool(env_name: str) -> bool:
    return bool(os.getenv(env_name))


def env_loaded_any(env_names: list[str]) -> str:
    for env_name in env_names:
        if os.getenv(env_name):
            return "Loaded"
    return "Missing"


def env_loaded_any_bool(env_names: list[str]) -> bool:
    for env_name in env_names:
        if os.getenv(env_name):
            return True
    return False


def pass_fail(condition: bool) -> str:
    return "✅ PASS" if condition else "❌ FAIL"


def info_status() -> str:
    return "ℹ️ INFO"


def format_uptime() -> str:
    uptime = datetime.now() - BOT_START_TIME

    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes > 0:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def get_cache_summary() -> tuple[int, int]:
    cache_count = 0
    cache_item_count = 0

    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("src."):
            continue

        for attr_name in dir(module):
            lower_name = attr_name.lower()

            if attr_name == "__cached__":
                continue

            try:
                attr = getattr(module, attr_name)
            except Exception:
                continue

            if "cache" in lower_name and isinstance(attr, dict):
                cache_count += 1
                cache_item_count += len(attr)

    return cache_count, cache_item_count


def clear_loaded_caches() -> list[str]:
    cleared_items = []

    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("src."):
            continue

        for attr_name in dir(module):
            lower_name = attr_name.lower()

            if attr_name == "__cached__":
                continue

            try:
                attr = getattr(module, attr_name)
            except Exception:
                continue

            if "cache" in lower_name and isinstance(attr, dict):
                size_before = len(attr)
                attr.clear()
                cleared_items.append(f"{module_name}.{attr_name} ({size_before} items)")
                continue

            if callable(attr) and hasattr(attr, "cache_clear"):
                try:
                    attr.cache_clear()
                    cleared_items.append(f"{module_name}.{attr_name} lru_cache")
                except Exception:
                    continue

    return cleared_items


def get_registered_command_count() -> int | str:
    try:
        from src.config.command_catalog import get_all_commands

        return len(get_all_commands())
    except Exception:
        return "unknown"


def get_command_scope_status(update: Update) -> str:
    current_chat_id = get_current_chat_id(update)
    command_chat_ids = get_command_chat_ids()

    if not command_chat_ids:
        return (
            "Telegram command exact-chat scope: Missing\n"
            f"Current chat ID: {current_chat_id}\n"
            "Dropdown fix: add this chat ID to TELEGRAM_COMMAND_CHAT_ID if the menu still shows an old command count."
        )

    current_scope_loaded = current_chat_id in command_chat_ids

    return (
        "Telegram command exact-chat scope: Loaded\n"
        f"Current chat ID: {current_chat_id}\n"
        f"Configured command chat IDs: {', '.join(sorted(command_chat_ids))}\n"
        f"Current chat has exact command scope: {'Yes' if current_scope_loaded else 'No'}"
    )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    start_time = time.perf_counter()

    sent_message = await update.message.reply_text("🏓 Pong...", parse_mode=None)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    await sent_message.edit_text(
        "🏓 Pong\n\n"
        f"Telegram response latency: {latency_ms} ms\n"
        f"Bot uptime: {format_uptime()}\n"
        "Status: Online",
        parse_mode=None,
    )


async def diagnostics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)
    admin_chat_ids = get_admin_chat_ids()
    command_chat_ids = get_command_chat_ids()
    cache_count, cache_item_count = get_cache_summary()

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    telegram_token_ok = env_loaded_bool("TELEGRAM_BOT_TOKEN")
    openai_key_ok = env_loaded_bool("OPENAI_API_KEY")
    sec_user_agent_ok = env_loaded_any_bool(["SEC_USER_AGENT", "SEC_API_USER_AGENT"])
    admin_ids_ok = bool(admin_chat_ids)
    admin_authorized_ok = current_chat_id in admin_chat_ids
    chat_id_ok = current_chat_id != "UNKNOWN"
    project_path_ok = bool(os.getcwd())
    python_ok = bool(platform.python_version())
    command_catalog_count = get_registered_command_count()

    await update.message.reply_text(
        "🧪 Smart Money AI Diagnostics\n\n"
        "Core Checks\n"
        f"{pass_fail(chat_id_ok)} Telegram chat detected\n"
        f"{pass_fail(admin_ids_ok)} Admin IDs loaded\n"
        f"{pass_fail(admin_authorized_ok)} Current chat authorized\n"
        f"{pass_fail(telegram_token_ok)} Telegram token loaded\n"
        f"{pass_fail(openai_key_ok)} OpenAI key loaded\n"
        f"{pass_fail(sec_user_agent_ok)} SEC user agent loaded\n\n"
        "Command Menu Checks\n"
        f"{info_status()} Command catalog count: {command_catalog_count}\n"
        f"{info_status()} TELEGRAM_COMMAND_CHAT_ID loaded: {'Yes' if command_chat_ids else 'No'}\n"
        f"{info_status()} Current chat in exact command scope: {'Yes' if current_chat_id in command_chat_ids else 'No'}\n\n"
        "Runtime Checks\n"
        f"{pass_fail(python_ok)} Python runtime available\n"
        f"{pass_fail(project_path_ok)} Project path detected\n"
        f"{info_status()} Python version: {platform.python_version()}\n"
        f"{info_status()} Platform: {platform.system()} {platform.release()}\n"
        f"{info_status()} Project path: {os.getcwd()}\n"
        f"{info_status()} Uptime: {format_uptime()}\n\n"
        "Cache Checks\n"
        f"{info_status()} Loaded cache objects: {cache_count}\n"
        f"{info_status()} Cached items detected: {cache_item_count}\n\n"
        "Admin Context\n"
        f"{info_status()} Current chat ID: {current_chat_id}\n"
        f"{info_status()} Authorized admin ID count: {len(admin_chat_ids)}\n\n"
        "Dropdown Troubleshooting\n"
        f"{get_command_scope_status(update)}\n\n"
        "Result\n"
        "Diagnostics completed.",
        parse_mode=None,
    )


async def clearcache(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    cleared_items = clear_loaded_caches()

    if cleared_items:
        cleared_display = "\n".join(f"- {item}" for item in cleared_items[:20])

        await update.message.reply_text(
            "✅ Cache cleared successfully.\n\n"
            f"Cleared:\n{cleared_display}",
            parse_mode=None,
        )
    else:
        await update.message.reply_text(
            "✅ Cache clear command completed.\n\n"
            "No loaded cache dictionaries or lru_cache functions were found to clear.",
            parse_mode=None,
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)
    admin_chat_ids = get_admin_chat_ids()
    command_chat_ids = get_command_chat_ids()
    cache_count, cache_item_count = get_cache_summary()
    command_catalog_count = get_registered_command_count()

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    await update.message.reply_text(
        "📊 Smart Money AI Status\n\n"
        "Bot\n"
        "Online: Yes\n"
        "Admin authorized: Yes\n"
        f"Current chat ID: {current_chat_id}\n"
        f"Authorized admin IDs loaded: {'Yes' if admin_chat_ids else 'No'}\n"
        f"Authorized admin ID count: {len(admin_chat_ids)}\n\n"
        "Environment\n"
        f"Telegram token: {env_loaded('TELEGRAM_BOT_TOKEN')}\n"
        f"OpenAI key: {env_loaded('OPENAI_API_KEY')}\n"
        f"SEC user agent: {env_loaded_any(['SEC_USER_AGENT', 'SEC_API_USER_AGENT'])}\n"
        f"Telegram admin IDs: {env_loaded('TELEGRAM_ADMIN_CHAT_ID')}\n"
        f"Telegram exact command chat IDs: {'Loaded' if command_chat_ids else 'Missing'}\n\n"
        "Command Menu\n"
        f"Command catalog count: {command_catalog_count}\n"
        f"Current chat exact command scope: {'Yes' if current_chat_id in command_chat_ids else 'No'}\n"
        "Manual command routing: Working if commands respond when typed manually\n"
        "Dropdown source: Telegram Bot API command scopes/cache\n\n"
        "Runtime\n"
        f"Python version: {platform.python_version()}\n"
        f"Platform: {platform.system()} {platform.release()}\n"
        f"Project path: {os.getcwd()}\n"
        f"Uptime: {format_uptime()}\n\n"
        "Cache\n"
        f"Loaded cache objects: {cache_count}\n"
        f"Cached items detected: {cache_item_count}\n\n"
        "Smart Money Summary\n"
        "/contextstatus - Provider status for the Smart Money Summary\n"
        "/summarypreview - Preview the current Smart Money Summary\n\n"
        "Maintenance\n"
        "/ping - Test bot responsiveness\n"
        "/diagnostics - Run admin diagnostics\n"
        "/clearcache - Clear loaded caches\n"
        "/admin - Show admin tools",
        parse_mode=None,
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)
    admin_chat_ids = get_admin_chat_ids()
    command_chat_ids = get_command_chat_ids()
    command_catalog_count = get_registered_command_count()

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}\n\n"
            "To authorize this chat, add this ID to TELEGRAM_ADMIN_CHAT_ID in your .env file.",
            parse_mode=None,
        )
        return

    authorized_ids_display = ", ".join(sorted(admin_chat_ids)) if admin_chat_ids else "None configured"
    command_ids_display = ", ".join(sorted(command_chat_ids)) if command_chat_ids else "None configured"

    await update.message.reply_text(
        "🛠 Smart Money AI Admin Panel\n\n"
        "Admin Status\n"
        "Status: Authorized\n"
        f"Current chat ID: {current_chat_id}\n"
        f"Authorized admin chat IDs: {authorized_ids_display}\n\n"
        "Telegram Dropdown Status\n"
        f"Command catalog count: {command_catalog_count}\n"
        f"Exact command chat IDs: {command_ids_display}\n"
        f"Current chat exact command scope: {'Yes' if current_chat_id in command_chat_ids else 'No'}\n\n"
        "If the dropdown still shows 44 commands but manual commands work:\n"
        "1. Add the Current chat ID above to TELEGRAM_COMMAND_CHAT_ID in .env.\n"
        "2. Rerun scripts/sync_telegram_commands.py on the server.\n"
        "3. Fully close and reopen Telegram.\n\n"
        "Smart Money Summary Commands\n"
        "/contextstatus - Provider status for the Smart Money Summary\n"
        "/summarypreview - Preview the current Smart Money Summary\n\n"
        "Quick Maintenance\n"
        "/ping - Test bot responsiveness\n"
        "/status - Show bot status dashboard\n"
        "/diagnostics - Run admin diagnostics\n"
        "/health - Check bot health\n"
        "/system - Show system information\n"
        "/version - Show bot version\n"
        "/commands - Show full command list\n"
        "/clearcache - Clear loaded caches\n\n"
        "Market Intelligence\n"
        "/brief\n"
        "/report\n"
        "/top10\n"
        "/snapshot\n"
        "/headlines\n"
        "/newsintel\n"
        "/macronews\n"
        "/tickernews SYMBOL\n"
        "/global\n"
        "/calendar\n\n"
        "Alerts\n"
        "/alerts\n"
        "/dailyalerts\n"
        "/alertstatus\n"
        "/alertrules\n"
        "/alertsettings\n"
        "/alertpreset balanced\n\n"
        "Stock Research\n"
        "/stock SYMBOL\n"
        "/stockdata SYMBOL\n"
        "/quote SYMBOL\n"
        "/market SYMBOL\n"
        "/scorecard SYMBOL\n"
        "/analyst SYMBOL\n"
        "/risk SYMBOL\n"
        "/earnings SYMBOL\n"
        "/volume SYMBOL\n"
        "/sec SYMBOL\n"
        "/filing SYMBOL\n\n"
        "Smart Money Intelligence\n"
        "/smartmoney\n"
        "/conviction\n"
        "/congress\n"
        "/insiders\n"
        "/defense\n"
        "/portfolio\n"
        "/growth\n"
        "/dividends\n"
        "/undervalued",
        parse_mode=None,
    )