import os
from dotenv import load_dotenv
from openai import OpenAI

from src.scoring.stock_lookup import get_stock
from src.scoring.risk_engine import get_risk_profile
from src.market.market_data import get_market_data, format_number, format_percent
from src.market.earnings_data import get_earnings_data
from src.sec.sec_data import get_sec_filings

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def safe_value(value):
    if value is None:
        return "N/A"
    return value


def build_sec_summary(symbol):
    try:
        data = get_sec_filings(symbol, limit=3)

        if not data["found"]:
            return "SEC filings unavailable."

        text = ""

        for filing in data["filings"][:3]:
            text += (
                f"- {filing['form']} | Filed: {filing['filing_date']} | "
                f"Report Date: {filing['report_date']}\n"
            )

        return text.strip()

    except Exception as error:
        return f"SEC filings unavailable: {error}"


def generate_scorecard_takeaway(stock, risk_profile, market_data, earnings_data, sec_summary):
    prompt = f"""
You are the Senior Analyst for Smart Money AI.

Create a clear investor-friendly scorecard takeaway using the data below.

Ticker: {stock['ticker']}
Category: {stock['category']}

Smart Score: {stock['smart_score']}
Defense Score: {stock['defense_score']}
Congress Score: {stock.get('congress_score', 0)}
Insider Score: {stock.get('insider_score', 0)}
Final Score: {stock['final_score']}

Risk Level: {risk_profile['risk_level']}
Risk Score: {risk_profile['risk_score']}/100
Risk Factors: {', '.join(risk_profile['risk_factors'])}

Company: {market_data.get('company_name', 'N/A') if market_data.get('found') else 'N/A'}
Price: {market_data.get('price', 'N/A') if market_data.get('found') else 'N/A'}
Market Cap: {format_number(market_data.get('market_cap')) if market_data.get('found') else 'N/A'}
P/E: {market_data.get('pe_ratio', 'N/A') if market_data.get('found') else 'N/A'}
Forward P/E: {market_data.get('forward_pe', 'N/A') if market_data.get('found') else 'N/A'}
Dividend Yield: {format_percent(market_data.get('dividend_yield')) if market_data.get('found') else 'N/A'}
Beta: {market_data.get('beta', 'N/A') if market_data.get('found') else 'N/A'}

Revenue: {format_number(earnings_data.get('revenue')) if earnings_data.get('found') else 'N/A'}
Revenue Growth: {format_percent(earnings_data.get('revenue_growth')) if earnings_data.get('found') else 'N/A'}
Net Income: {format_number(earnings_data.get('net_income')) if earnings_data.get('found') else 'N/A'}
Gross Margin: {format_percent(earnings_data.get('gross_margin')) if earnings_data.get('found') else 'N/A'}
Operating Margin: {format_percent(earnings_data.get('operating_margin')) if earnings_data.get('found') else 'N/A'}
Net Margin: {format_percent(earnings_data.get('net_margin')) if earnings_data.get('found') else 'N/A'}

Recent SEC Filings:
{sec_summary}

Return a concise scorecard with:

1. Overall rating
2. Bull case
3. Risk case
4. Valuation / earnings view
5. Smart Money AI takeaway

Maximum 200 words.
End with: "This is research, not financial advice."
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    return response.output_text


def build_scorecard(symbol):
    symbol = symbol.upper()

    stock = get_stock(symbol)

    if not stock:
        return {
            "found": False,
            "message": f"{symbol} not found in watchlist."
        }

    risk_profile = get_risk_profile(stock)
    market_data = get_market_data(symbol)
    earnings_data = get_earnings_data(symbol)
    sec_summary = build_sec_summary(symbol)

    if market_data.get("found"):
        market_section = f"""
Company:
{market_data['company_name']}

Price:
${market_data['price']:.2f}

Market Cap:
{format_number(market_data['market_cap'])}

P/E:
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
        market_section = "Market data unavailable."

    if earnings_data.get("found"):
        earnings_section = f"""
Period:
{earnings_data['period_type']} - {earnings_data['latest_period']}

Revenue:
{format_number(earnings_data['revenue'])}

Revenue Growth:
{format_percent(earnings_data['revenue_growth'])}

Net Income:
{format_number(earnings_data['net_income'])}

Gross Margin:
{format_percent(earnings_data['gross_margin'])}

Operating Margin:
{format_percent(earnings_data['operating_margin'])}

Net Margin:
{format_percent(earnings_data['net_margin'])}
"""
    else:
        earnings_section = "Earnings data unavailable."

    try:
        ai_takeaway = generate_scorecard_takeaway(
            stock,
            risk_profile,
            market_data,
            earnings_data,
            sec_summary
        )
    except Exception as error:
        ai_takeaway = f"AI takeaway unavailable: {error}"

    message = f"""
🧾 SMART MONEY SCORECARD: {stock['ticker']}

Category:
{stock['category']}

SMART MONEY SCORES

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

RISK PROFILE

Risk Level:
{risk_profile['risk_level']}

Risk Score:
{risk_profile['risk_score']}/100

MARKET DATA

{market_section}

EARNINGS DATA

{earnings_section}

RECENT SEC FILINGS

{sec_summary}

AI SCORECARD TAKEAWAY

{ai_takeaway}
"""

    return {
        "found": True,
        "message": message.strip()
    }