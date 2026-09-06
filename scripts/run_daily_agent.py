import argparse
import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.jobs.daily_agent_job import format_daily_agent_result, run_daily_agent


MAX_TELEGRAM_CHARS = 3800


def split_text(text: str, limit: int = MAX_TELEGRAM_CHARS) -> list[str]:
    text = str(text or "").strip()

    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

    for paragraph in text.split("\n\n"):
        addition = paragraph if not current else "\n\n" + paragraph

        if len(current) + len(addition) <= limit:
            current += addition
        else:
            if current:
                chunks.append(current)

            if len(paragraph) <= limit:
                current = paragraph
            else:
                for index in range(0, len(paragraph), limit):
                    chunks.append(paragraph[index:index + limit])
                current = ""

    if current:
        chunks.append(current)

    return chunks


async def send_to_telegram(text: str) -> None:
    from telegram import Bot

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = (
        os.getenv("TELEGRAM_CHANNEL_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("TELEGRAM_COMMAND_CHAT_ID")
    )

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

    if not chat_id:
        raise RuntimeError("TELEGRAM_CHANNEL_ID, TELEGRAM_CHAT_ID, or TELEGRAM_COMMAND_CHAT_ID is missing.")

    bot = Bot(token=token)

    for chunk in split_text(text):
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            parse_mode=None,
            disable_web_page_preview=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Smart Money Daily Agent.")
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send the generated daily report to Telegram.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without live refresh steps.",
    )

    args = parser.parse_args()

    result = run_daily_agent(dry_run=args.dry_run)
    status_message = format_daily_agent_result(result)

    print(status_message)

    if args.send_telegram:
        report = result.get("report", "")

        if not result.get("success"):
            print("")
            print("Telegram send skipped because agent status failed.")
            return 1

        if not report:
            print("")
            print("Telegram send skipped because no report was generated.")
            return 1

        asyncio.run(send_to_telegram(report))
        print("")
        print("Telegram send complete.")

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
