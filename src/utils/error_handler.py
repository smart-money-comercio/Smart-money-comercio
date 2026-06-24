import traceback

from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error

    if isinstance(error, RetryAfter):
        print(f"Telegram rate limit hit. Retry after {error.retry_after} seconds.")
        return

    if isinstance(error, TimedOut):
        print("Telegram request timed out. The bot will continue running.")
        return

    if isinstance(error, NetworkError):
        print("Telegram network issue detected. The bot will keep trying.")
        return

    if isinstance(error, TelegramError):
        print(f"Telegram error: {error}")
        return

    print("Unexpected bot error:")
    print(error)
    traceback.print_exception(type(error), error, error.__traceback__)