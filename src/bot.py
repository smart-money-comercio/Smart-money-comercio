import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from src.agents.analyst_agent import analyze_stock
from src.congress.congress_scoring import get_congress_trades
from src.insiders.insider_scoring import get_insider_trades
from src.reports.daily_report import build_daily_report
from src.scoring.scoring_engine import get_stock_scores
from src.scoring.stock_lookup import get_stock
from src.scoring.risk_engine import get_risk_profile
from src.market.market_data import get_market_data, format_number, format_percent
from src.sec.sec_data import get_sec_filings
from src.sec.sec_summary import summarize_sec_filing
from src.market.earnings_data import get_earnings_data, summarize_earnings
from src.reports.scorecard import build_scorecard
from src.screeners.undervalued_screener import get_undervalued_ideas
from src.commands.register_commands import register_commands

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def congress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_congress_trades()
    text = "🏛️ CONGRESSIONAL TRADING INTELLIGENCE\n\n"

    for trade in trades:
        text += (
            f"{trade['politician']}\n"
            f"{trade['transaction']}: {trade['ticker']}\n"
            f"Sector: {trade['sector']}\n"
            f"Amount: {trade['amount_range']}\n\n"
        )

    await update.message.reply_text(text)

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

async def earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /earnings PLTR")
        return

    symbol = context.args[0].upper()

    await update.message.reply_text(
        f"📊 Pulling earnings data for {symbol}..."
    )

    data = get_earnings_data(symbol)

    if not data["found"]:
        await update.message.reply_text(
            f"Earnings data not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    try:
        ai_summary = summarize_earnings(data)
    except Exception as error:
        ai_summary = f"AI summary unavailable: {error}"

    message = f"""
📊 EARNINGS SNAPSHOT: {data['ticker']}

Company:
{data['company_name']}

Period:
{data['period_type']} - {data['latest_period']}

Sector:
{data['sector']}

Revenue:
{format_number(data['revenue'])}

Revenue Growth:
{format_percent(data['revenue_growth'])}

Gross Profit:
{format_number(data['gross_profit'])}

Operating Income:
{format_number(data['operating_income'])}

Net Income:
{format_number(data['net_income'])}

EPS:
{data['diluted_eps'] if data['diluted_eps'] else 'N/A'}

Gross Margin:
{format_percent(data['gross_margin'])}

Operating Margin:
{format_percent(data['operating_margin'])}

Net Margin:
{format_percent(data['net_margin'])}

P/E Ratio:
{data['pe_ratio'] if data['pe_ratio'] else 'N/A'}

Forward P/E:
{data['forward_pe'] if data['forward_pe'] else 'N/A'}

Dividend Yield:
{format_percent(data['dividend_yield'])}

🧠 AI EARNINGS SUMMARY

{ai_summary}
"""

    await update.message.reply_text(message)

async def scorecard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scorecard PLTR")
        return

    symbol = context.args[0].upper()

    await update.message.reply_text(
        f"🧾 Building Smart Money scorecard for {symbol}..."
    )

    result = build_scorecard(symbol)

    await update.message.reply_text(result["message"])

async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = sorted(
        get_stock_scores(),
        key=lambda x: (
            x.get("congress_score", 0)
            + x.get("insider_score", 0)
        ),
        reverse=True
    )

    text = "🧠 SMART MONEY SIGNALS\n\n"

    for stock in scores[:5]:
        text += (
            f"{stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Congress Score: {stock.get('congress_score', 0)}\n"
            f"Insider Score: {stock.get('insider_score', 0)}\n"
            f"Final Score: {stock['final_score']}\n\n"
        )

    text += (
        "🧠 Insight:\n"
        "Smart Money signals combine congressional activity and insider buying. "
        "These are research inputs, not standalone buy recommendations."
    )

    await update.message.reply_text(text)


async def insiders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_insider_trades()
    text = "🏢 INSIDER BUYING INTELLIGENCE\n\n"

    for trade in trades:
        text += (
            f"{trade['insider']}\n"
            f"{trade['transaction']}: {trade['ticker']}\n"
            f"Sector: {trade['sector']}\n"
            f"Amount: {trade['amount_range']}\n"
            f"Date: {trade['date']}\n\n"
        )

    await update.message.reply_text(text)


async def conviction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = sorted(
        get_stock_scores(),
        key=lambda x: (
            x.get("congress_score", 0)
            + x.get("insider_score", 0)
            + x.get("defense_score", 0)
        ),
        reverse=True
    )

    text = "🔥 HIGH CONVICTION IDEAS\n\n"

    for stock in scores[:5]:
        congress_score = stock.get("congress_score", 0)
        insider_score = stock.get("insider_score", 0)
        defense_score = stock.get("defense_score", 0)

        risk_profile = get_risk_profile(stock)

        overlap_count = 0

        if congress_score > 0:
            overlap_count += 1

        if insider_score > 0:
            overlap_count += 1

        if defense_score >= 85:
            overlap_count += 1

        text += (
            f"{stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Defense Score: {defense_score}\n"
            f"Congress Score: {congress_score}\n"
            f"Insider Score: {insider_score}\n"
            f"Final Score: {stock['final_score']}\n"
            f"Signal Overlap: {overlap_count}/3\n"
            f"Risk Level: {risk_profile['risk_level']}\n"
            f"Risk Score: {risk_profile['risk_score']}/100\n\n"
        )

    text += (
        "Note: High conviction means multiple research signals overlap. "
        "Risk level is shown to prevent confusing high conviction with low risk. "
        "This is not financial advice."
    )

    await update.message.reply_text(text)

async def realcongress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_real_congress_trades(limit=10)

    if not trades:
        await update.message.reply_text("No congressional trades found.")
        return

    text = "🏛️ REAL CONGRESSIONAL DISCLOSURES\n\n"

    for trade in trades:
        text += (
            f"{trade['politician']} ({trade['source']})\n"
            f"{trade['transaction']}: {trade['ticker']}\n"
            f"Amount: {trade['amount_range']}\n"
            f"Disclosure: {trade['disclosure_date']}\n\n"
        )

    await update.message.reply_text(text)

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /market PLTR")
        return

    symbol = context.args[0].upper()
    data = get_market_data(symbol)

    if not data["found"]:
        await update.message.reply_text(
            f"Market data not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    message = f"""
📊 MARKET DATA: {data['ticker']}

Company:
{data['company_name']}

Sector:
{data['sector']}

Industry:
{data['industry']}

Price:
${data['price']:.2f}

Market Cap:
{format_number(data['market_cap'])}

P/E Ratio:
{data['pe_ratio'] if data['pe_ratio'] else 'N/A'}

Forward P/E:
{data['forward_pe'] if data['forward_pe'] else 'N/A'}

Dividend Yield:
{format_percent(data['dividend_yield'])}

Beta:
{data['beta'] if data['beta'] else 'N/A'}

52-Week High:
${data['week_52_high']:.2f}

52-Week Low:
${data['week_52_low']:.2f}

Note:
Market data is pulled from a public market-data source and should be verified before making investment decisions.
"""

    await update.message.reply_text(message) 

async def undervalued(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 Scanning watchlist for undervalued ideas..."
    )

    try:
        ideas = get_undervalued_ideas(limit=10)
    except Exception as error:
        await update.message.reply_text(
            f"Undervalued screen error:\n{error}"
        )
        return

    if not ideas:
        await update.message.reply_text(
            "No undervalued ideas found based on the current screen."
        )
        return

    text = "💎 UNDERVALUED SMART MONEY IDEAS\n\n"

    for i, idea in enumerate(ideas, start=1):
        reasons = ", ".join(idea["reasons"][:3])

        price_text = f"${idea['price']:.2f}" if idea["price"] else "N/A"
        pe_text = idea["pe_ratio"] if idea["pe_ratio"] else "N/A"
        forward_pe_text = idea["forward_pe"] if idea["forward_pe"] else "N/A"

        text += (
            f"{i}. {idea['ticker']}\n"
            f"Category: {idea['category']}\n"
            f"Price: {price_text}\n"
            f"Smart Money Score: {idea['final_score']}\n"
            f"Undervalued Score: {idea['undervalued_score']}\n"
            f"Risk: {idea['risk_level']} ({idea['risk_score']}/100)\n"
            f"P/E: {pe_text}\n"
            f"Forward P/E: {forward_pe_text}\n"
            f"Dividend Yield: {format_percent(idea['dividend_yield'])}\n"
            f"Why: {reasons}\n\n"
        )

    text += (
        "Note: This screen looks for strong Smart Money scores, reasonable valuation, "
        "earnings support, dividend support, and manageable risk. "
        "This is research, not financial advice."
    )

    await update.message.reply_text(text)

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /risk PLTR")
        return

    symbol = context.args[0].upper()
    stock = get_stock(symbol)

    if not stock:
        await update.message.reply_text(f"{symbol} not found in watchlist.")
        return

    risk_profile = get_risk_profile(stock)

    factors = "\n".join(
        [f"- {factor}" for factor in risk_profile["risk_factors"]]
    )

    message = f"""
⚠️ RISK PROFILE: {risk_profile['ticker']}

Risk Level:
{risk_profile['risk_level']}

Risk Score:
{risk_profile['risk_score']}/100

Category:
{stock['category']}

Key Risk Factors:
{factors}

Note:
This risk score is a research estimate based on category, volatility profile, and concentration risk. It is not financial advice.
"""

    await update.message.reply_text(message)

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /quote PLTR")
        return

    symbol = context.args[0].upper()
    data = get_market_data(symbol)

    if not data["found"]:
        await update.message.reply_text(
            f"Quote not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    message = f"""
💹 QUOTE: {data['ticker']}

Company:
{data['company_name']}

Price:
${data['price']:.2f}

Market Cap:
{format_number(data['market_cap'])}

P/E Ratio:
{data['pe_ratio'] if data['pe_ratio'] else 'N/A'}

Forward P/E:
{data['forward_pe'] if data['forward_pe'] else 'N/A'}

Dividend Yield:
{format_percent(data['dividend_yield'])}

Beta:
{data['beta'] if data['beta'] else 'N/A'}

52-Week Range:
${data['week_52_low']:.2f} - ${data['week_52_high']:.2f}
"""

    await update.message.reply_text(message)

async def ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text("Usage: /ticker PLTR")
        return

    symbol = context.args[0].upper()
    stock = get_stock(symbol)

    if not stock:
        await update.message.reply_text(f"{symbol} not found in watchlist.")
        return

    risk_profile = get_risk_profile(stock)
    market_data = get_market_data(symbol)
    analysis = analyze_stock(stock)

    if market_data["found"]:
        market_section = f"""
📊 MARKET DATA

Company:
{market_data['company_name']}

Price:
${market_data['price']:.2f}

Market Cap:
{format_number(market_data['market_cap'])}

P/E Ratio:
{market_data['pe_ratio'] if market_data['pe_ratio'] else 'N/A'}

Forward P/E:
{market_data['forward_pe'] if market_data['forward_pe'] else 'N/A'}

Dividend Yield:
{format_percent(market_data['dividend_yield'])}

Beta:
{market_data['beta'] if market_data['beta'] else 'N/A'}

52-Week Range:
${market_data['week_52_low']:.2f} - ${market_data['week_52_high']:.2f}
"""
    else:
        market_section = """
📊 MARKET DATA

Market data unavailable.
"""

    message = f"""
📈 {stock['ticker']}

Category:
{stock['category']}

Smart Score:
{stock['smart_score']}

Defense Score:
{stock['defense_score']}

Congress Score:
{stock.get('congress_score', 0)}

Insider Score:
{stock.get('insider_score', 0)}

Final Score:
{stock['final_score']}

⚠️ RISK PROFILE

Risk Level:
{risk_profile['risk_level']}

Risk Score:
{risk_profile['risk_score']}/100

{market_section}

🧠 AI ANALYSIS

{analysis}
"""

    await update.message.reply_text(message)


def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing from .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    commands = {
        "ticker": ticker,
        "quote": quote,
        "market": market,
        "earnings": earnings,
        "scorecard": scorecard,

        "risk": risk,
        "conviction": conviction,
        "smartmoney": smartmoney,
        "undervalued": undervalued,

        "congress": congress,
        "insiders": insiders,
        "sec": sec,
        "filing": filing,
    }

    register_commands(app, commands)

    print("Smart Money AI bot is running...")
    app.run_polling()         


if __name__ == "__main__":
    main()