from telegram import Update
from telegram.ext import ContextTypes

from src.agents.analyst_agent import analyze_stock
from src.market.earnings_data import get_earnings_data, summarize_earnings
from src.market.market_data import get_market_data, format_number, format_percent
from src.reports.scorecard import build_scorecard
from src.scoring.risk_engine import get_risk_profile
from src.scoring.stock_lookup import get_stock


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