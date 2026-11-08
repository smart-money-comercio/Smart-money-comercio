import asyncio
import logging

from telegram import Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import ContextTypes

from src.jobs.daily_agent_job import (
    format_daily_agent_result,
    run_daily_agent,
)
from src.reports.daily_agent_status_report import build_daily_agent_status_report
from src.utils.daily_agent_delivery import Receipt, error_note


MAX_TELEGRAM_CHARS = 3800
LOG = logging.getLogger(__name__)


async def edit_status(message, text):
    # Editing the same message with identical text is safe to repeat. A send is
    # deliberately not repeated after a read failure: Telegram may have accepted it.
    for attempt in range(2):
        try:
            return await message.edit_text(text, parse_mode=None, disable_web_page_preview=True)
        except BadRequest as error:
            if attempt and "message is not modified" in str(error).lower():return None
            raise
        except NetworkError:
            if attempt:raise
            await asyncio.sleep(0.25)


def problem_text(result, receipt):
    value = receipt.value
    workflow = "PASS" if result and result.get("success") else "FAIL"
    lines = ["Smart Money Daily Agent", "Status: "+workflow]
    if result:
        lines += ["Research workflow: "+workflow, "Last Run: "+str(result.get("last_run") or "unavailable"),
            "Telegram reply: "+value["state"].upper(), "Stopped at: "+value["stage"],
            f"Confirmed report parts: {value['report_confirmed']}/{value['report_total']}"]
        if value["part"]:lines.append(f"Affected part: {value['part']}/{value['total']}")
    else:
        lines += ["Stage: research workflow did not return a result", "A previous saved run cannot confirm this request."]
    lines += ["Error: "+value["error"], "", "/agentstatus checks the saved run and reply receipt.", "/quality checks the brief."]
    return "\n".join(lines)


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

    receipt = Receipt()
    loading_message = None
    result = None
    try:
        receipt.update(stage="loading_notice")
        loading_message = await update.message.reply_text("Running Smart Money Daily Agent...", parse_mode=None)
        receipt.update(loading_notice="confirmed")
    except TelegramError as error:
        # This acknowledgement is advisory; the requested workflow still runs once.
        receipt.update(loading_notice="unconfirmed" if isinstance(error, NetworkError) and not isinstance(error, BadRequest) else "rejected")
        LOG.warning("Daily agent loading notice unconfirmed error=%s", error_note(error))

    try:
        receipt.update(stage="research_workflow", part=0, total=0)
        result = await asyncio.to_thread(run_daily_agent, False)
        receipt.result(result, 0, 0)
        receipt.update(stage="format_status")
        status_message = format_daily_agent_result(result)
        status_chunks = split_text(status_message)
        report = result.get("report", "")
        report_chunks = split_text(report) if result.get("success") and report else []
        receipt.result(result, len(status_chunks), len(report_chunks))

        receipt.update(stage="status_edit" if loading_message else "status_part", part=1, total=len(status_chunks))
        if loading_message:
            await edit_status(loading_message, status_chunks[0])
        else:
            await update.effective_chat.send_message(text=status_chunks[0], parse_mode=None, disable_web_page_preview=True)
        receipt.update(status_confirmed=1)
        for index, chunk in enumerate(status_chunks[1:], 2):
            receipt.update(stage="status_part", part=index, total=len(status_chunks))
            await update.effective_chat.send_message(
                text=chunk,
                parse_mode=None,
                disable_web_page_preview=True,
            )
            receipt.update(status_confirmed=index)

        for index, chunk in enumerate(report_chunks, 1):
            receipt.update(stage="brief_part", part=index, total=len(report_chunks))
            await update.effective_chat.send_message(text=chunk, parse_mode=None, disable_web_page_preview=True)
            receipt.update(report_confirmed=index)
        receipt.update(state="confirmed", stage="complete", part=0, total=0)

    except Exception as error:
        state = ("workflow_error" if result is None else "unconfirmed" if isinstance(error, NetworkError) and not isinstance(error, BadRequest)
                 else "failed" if isinstance(error, TelegramError) else "interrupted")
        receipt.update(state=state, error=error_note(error))
        LOG.warning("Daily agent command interrupted run=%s stage=%s part=%s/%s workflow=%s error=%s",
            receipt.value["run_id"], receipt.value["stage"], receipt.value["part"], receipt.value["total"],
            receipt.value["workflow_status"], receipt.value["error"])
        # Use the known message for an idempotent notice. Do not resend an uncertain
        # status/report send or regenerate the research to repair transport failure.
        if loading_message:
            try:await edit_status(loading_message, problem_text(result, receipt))
            except Exception as notice_error:
                receipt.update(notice_error=error_note(notice_error))
                LOG.warning("Daily agent failure notice unconfirmed error=%s", error_note(notice_error))


async def agentstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await agentstatus_command(update, context)


async def rundailyagent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await rundailyagent_command(update, context)
