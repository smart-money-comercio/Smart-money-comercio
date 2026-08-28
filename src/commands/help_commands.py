from src.config.command_catalog import build_commands_menu_text
from src.utils.telegram_messages import reply_long_message


async def commands_command(update, context) -> None:
    if not update.message:
        return

    await reply_long_message(
        update=update,
        text=build_commands_menu_text(),
        title="🤖 Smart Money AI Commands",
        parse_mode=None,
    )