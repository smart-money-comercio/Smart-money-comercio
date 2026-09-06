import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.jobs.daily_agent_job import (
    format_daily_agent_result,
    run_daily_agent,
)
from src.reports.daily_agent_status_report import build_daily_agent_status_report


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


async def send_long_plain_text(update: Update, text: str) -> None:
    if not update.effective_chat:
        return

    for chunk in split_text(text):
        await update.effective_chat.send_message(
            text=chunk,
            parse_mode=None,
            disable_web_page_preview=True,
        )


async def agentstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    message = build_daily_agent_status_report()

    await send_long_plain_text(update, message)


async def rundailyagent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "Running Smart Money Daily Agent...",
        parse_mode=None,
    )

    try:
        result = await asyncio.to_thread(run_daily_agent, False)
        status_message = format_daily_agent_result(result)

        await loading_message.edit_text(
            status_message[:MAX_TELEGRAM_CHARS],
            parse_mode=None,
            disable_web_page_preview=True,
        )

        report = result.get("report", "")

        if result.get("success") and report:
            await update.effective_chat.send_message(
                text="Daily Report Output",
                parse_mode=None,
            )
            await send_long_plain_text(update, report)

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money Daily Agent\n"
            "Status: FAIL\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def agentstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await agentstatus_command(update, context)


async def rundailyagent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await rundailyagent_command(update, context)
