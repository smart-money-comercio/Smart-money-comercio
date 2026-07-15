import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from src.reports.daily_report import build_daily_report


TELEGRAM_MAX_MESSAGE_LENGTH = 3900
REQUEST_TIMEOUT_SECONDS = 20


def get_env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()

        if value:
            return value

    return ""


def get_chat_ids() -> list[str]:
    raw = get_env_value(
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_CHANNEL_ID",
        "TELEGRAM_CHANNEL_IDS",
        "TELEGRAM_REPORT_CHAT_ID",
        "TELEGRAM_REPORT_CHAT_IDS",
        "DAILY_REPORT_CHAT_ID",
        "DAILY_REPORT_CHAT_IDS",
        "TELEGRAM_DAILY_REPORT_CHAT_ID",
        "TELEGRAM_DAILY_REPORT_CHAT_IDS",
    )

    if not raw:
        return []

    return [
        item.strip()
        for item in raw.replace(";", ",").split(",")
        if item.strip()
    ]


def split_long_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)

        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)

        if split_at == -1:
            split_at = limit

        chunk = remaining[:split_at].strip()

        if chunk:
            chunks.append(chunk)

        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def refresh_morning_brief_safely() -> None:
    try:
        from src.reports.morning_brief_intro import refresh_morning_brief_cache

        refresh_morning_brief_cache()
        print("Morning brief cache refreshed.")
    except Exception as error:
        print(f"Morning brief refresh skipped: {type(error).__name__}: {error}")


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = split_long_message(text)

    for index, chunk in enumerate(chunks, start=1):
        prefix = ""

        if len(chunks) > 1:
            prefix = f"Part {index}/{len(chunks)}\n\n"

        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": prefix + chunk,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        print(f"Chat {chat_id} | Part {index}/{len(chunks)} | Status: {response.status_code}")

        if not response.ok:
            print(response.text)
            response.raise_for_status()

        time.sleep(0.5)


def main() -> None:
    bot_token = get_env_value("TELEGRAM_BOT_TOKEN")
    chat_ids = get_chat_ids()

    if not bot_token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env")

    if not chat_ids:
        raise RuntimeError(
            "Missing Telegram chat/channel ID. Set one of: "
            "TELEGRAM_CHAT_ID, TELEGRAM_CHANNEL_ID, TELEGRAM_CHANNEL_IDS, "
            "TELEGRAM_REPORT_CHAT_ID, TELEGRAM_REPORT_CHAT_IDS, "
            "DAILY_REPORT_CHAT_ID, DAILY_REPORT_CHAT_IDS, "
            "TELEGRAM_DAILY_REPORT_CHAT_ID, TELEGRAM_DAILY_REPORT_CHAT_IDS"
        )

    refresh_morning_brief_safely()

    report = build_daily_report()

    if not report.strip():
        raise RuntimeError("Daily report returned empty text.")

    for chat_id in chat_ids:
        send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=report,
        )

    print("Daily report sent successfully.")


if __name__ == "__main__":
    main()