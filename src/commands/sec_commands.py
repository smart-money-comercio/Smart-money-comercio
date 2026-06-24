from telegram import Update
from telegram.ext import ContextTypes

from src.sec.sec_data import get_sec_filings
from src.sec.sec_summary import summarize_sec_filing


async def sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /sec PLTR")
        return

    symbol = context.args[0].upper()

    try:
        data = get_sec_filings(symbol, limit=5)
    except Exception as error:
        await update.message.reply_text(
            f"SEC data error for {symbol}:\n{error}"
        )
        return

    if not data["found"]:
        await update.message.reply_text(
            f"SEC filings not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    text = f"📄 SEC FILINGS: {data['ticker']}\n\n"
    text += f"Company: {data['company_name']}\n"
    text += f"CIK: {data['cik']}\n\n"

    for filing in data["filings"]:
        text += (
            f"{filing['form']}\n"
            f"Filed: {filing['filing_date']}\n"
            f"Report Date: {filing['report_date']}\n"
            f"Document: {filing['document']}\n"
            f"{filing['url']}\n\n"
        )

    text += (
        "Note: SEC filings are official regulatory documents. "
        "Review the full filing before making investment decisions."
    )

    await update.message.reply_text(text)


async def filing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /filing PLTR or /filing PLTR 10-K")
        return

    symbol = context.args[0].upper()

    form_filter = None
    if len(context.args) > 1:
        form_filter = context.args[1].upper()

    await update.message.reply_text(
        f"📄 Summarizing SEC filing for {symbol}..."
    )

    try:
        result = summarize_sec_filing(symbol, form_filter)
    except Exception as error:
        await update.message.reply_text(
            f"Filing summary error for {symbol}:\n{error}"
        )
        return

    if not result["found"]:
        await update.message.reply_text(
            f"Could not summarize filing for {symbol}.\n"
            f"Error: {result.get('error', 'Unknown error')}"
        )
        return

    message = f"""
📄 AI SEC FILING SUMMARY: {result['ticker']}

Company:
{result['company_name']}

Form:
{result['form']}

Filed:
{result['filing_date']}

Report Date:
{result['report_date']}

🧠 SUMMARY

{result['summary']}
"""

    await update.message.reply_text(message)