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

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Smart Money AI is online.\n\n"
        "Commands:\n"
        "/report - Latest full report\n"
        "/market SYMBOL - Real market data\n"
        "/quote SYMBOL - Fast market quote\n"
        "/top10 - Top ranked stocks\n"
        "/growth - Growth and AI stocks\n"
        "/dividends - Dividend and high-income stocks\n"
        "/congress - Congressional trading intelligence\n"
        "/defense - Defense rankings\n"
        "/watchlist - Tracked companies\n"
        "/ticker SYMBOL - Stock summary\n"
        "/smartmoney - Smart money signals\n"
        "/conviction - Highest signal-overlap ideas\n"
        "/insiders - Insider buying intelligence\n"
        "/realcongress - Real congressional disclosures\n"
        "/portfolio - Smart Money portfolio model\n"
        "/risk SYMBOL - Risk profile\n"
        "/help - Command list"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_daily_report())


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()
    text = "🔥 TOP 10 SMART MONEY PICKS\n\n"

    for i, stock in enumerate(scores[:10], start=1):
        text += f"{i}. {stock['ticker']} - {stock['final_score']} ({stock['category']})\n"

    await update.message.reply_text(text)

async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()

    growth = [
        stock for stock in scores
        if "Growth" in stock["category"] or "AI" in stock["category"]
    ]

    defense = [
        stock for stock in scores
        if (
            "Defense" in stock["category"]
            or "Cyber" in stock["category"]
            or "Drones" in stock["category"]
            or "Autonomous" in stock["category"]
            or "Space" in stock["category"]
            or "Missile" in stock["category"]
        )
    ]

    etfs = [
        stock for stock in scores
        if "ETF" in stock["category"]
    ]

    dividends = [
        stock for stock in scores
        if "Dividend" in stock["category"] or "High Dividend" in stock["category"]
    ]

    growth = sorted(growth, key=lambda x: x["final_score"], reverse=True)
    defense = sorted(defense, key=lambda x: x["final_score"], reverse=True)
    etfs = sorted(etfs, key=lambda x: x["final_score"], reverse=True)
    dividends = sorted(dividends, key=lambda x: x["final_score"], reverse=True)

    text = "📊 SMART MONEY PORTFOLIO MODEL\n\n"

    text += "🚀 Growth Allocation: 40%\n"
    for stock in growth[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += "\n🛡️ Defense / Cyber / AI Warfare Allocation: 20%\n"
    for stock in defense[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += "\n📈 ETF Allocation: 25%\n"
    for stock in etfs[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += "\n💰 Dividend / High-Income Allocation: 15%\n"
    for stock in dividends[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += (
        "\nNote: This is a research model based on Smart Money AI scoring. "
        "It is not financial advice. Review risk, valuation, dividend safety, and diversification before investing."
    )

    await update.message.reply_text(text)

async def defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = sorted(
        get_stock_scores(),
        key=lambda x: x["defense_score"],
        reverse=True
    )

    text = "🛡️ DEFENSE INTELLIGENCE RANKINGS\n\n"

    for i, stock in enumerate(scores[:10], start=1):
        text += (
            f"{i}. {stock['ticker']} - "
            f"Defense Score: {stock['defense_score']} "
            f"({stock['category']})\n"
        )

    await update.message.reply_text(text)


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()
    text = "📋 SMART MONEY WATCHLIST\n\n"

    for stock in scores:
        text += f"- {stock['ticker']} | {stock['category']}\n"

    await update.message.reply_text(text)


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

async def growth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()

    growth_stocks = [
        stock for stock in scores
        if "Growth" in stock["category"] or "AI" in stock["category"]
    ]

    growth_stocks = sorted(
        growth_stocks,
        key=lambda x: x["final_score"],
        reverse=True
    )

    text = "🚀 GROWTH & AI STOCKS\n\n"

    for i, stock in enumerate(growth_stocks[:10], start=1):
        text += (
            f"{i}. {stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Final Score: {stock['final_score']}\n\n"
        )

    text += (
        "Note: Growth stocks can have higher upside but also higher volatility. "
        "This is research, not financial advice."
    )

    await update.message.reply_text(text)


async def dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()

    dividend_stocks = [
        stock for stock in scores
        if "Dividend" in stock["category"] or "High Dividend" in stock["category"]
    ]

    dividend_stocks = sorted(
        dividend_stocks,
        key=lambda x: x["final_score"],
        reverse=True
    )

    text = "💰 DIVIDEND & HIGH-INCOME STOCKS\n\n"

    for i, stock in enumerate(dividend_stocks[:10], start=1):
        text += (
            f"{i}. {stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Final Score: {stock['final_score']}\n\n"
        )

    text += (
        "Note: Dividend stocks may provide income, but yield and safety should be reviewed separately. "
        "This is research, not financial advice."
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("top10", top10))
    app.add_handler(CommandHandler("defense", defense))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("congress", congress))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("insiders", insiders))
    app.add_handler(CommandHandler("conviction", conviction))
    app.add_handler(CommandHandler("realcongress", realcongress))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("dividends", dividends))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("quote", quote))

    print("Smart Money AI bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()