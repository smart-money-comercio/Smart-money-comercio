import os
import yfinance as yf
from dotenv import load_dotenv
from openai import OpenAI

from src.market.market_data import format_number, format_percent

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_statement_value(statement, row_names, column):
    if statement is None or statement.empty:
        return None

    for row_name in row_names:
        if row_name in statement.index:
            value = statement.loc[row_name, column]
            try:
                return float(value)
            except Exception:
                return None

    return None


def calculate_growth(current, previous):
    if current is None or previous is None or previous == 0:
        return None

    try:
        return ((current - previous) / abs(previous)) * 100
    except Exception:
        return None


def calculate_margin(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None

    try:
        return numerator / denominator
    except Exception:
        return None


def get_earnings_data(ticker):
    try:
        symbol = ticker.upper()
        stock = yf.Ticker(symbol)

        info = stock.info or {}

        quarterly_statement = stock.quarterly_income_stmt
        annual_statement = stock.income_stmt

        if quarterly_statement is not None and not quarterly_statement.empty:
            statement = quarterly_statement
            period_type = "Quarterly"
        elif annual_statement is not None and not annual_statement.empty:
            statement = annual_statement
            period_type = "Annual"
        else:
            return {
                "found": False,
                "ticker": symbol,
                "error": "No income statement data found"
            }

        columns = list(statement.columns)

        if not columns:
            return {
                "found": False,
                "ticker": symbol,
                "error": "No reporting periods found"
            }

        latest_period = columns[0]
        previous_period = columns[1] if len(columns) > 1 else None

        revenue = get_statement_value(
            statement,
            ["Total Revenue", "Operating Revenue"],
            latest_period
        )

        previous_revenue = None
        if previous_period is not None:
            previous_revenue = get_statement_value(
                statement,
                ["Total Revenue", "Operating Revenue"],
                previous_period
            )

        gross_profit = get_statement_value(
            statement,
            ["Gross Profit"],
            latest_period
        )

        operating_income = get_statement_value(
            statement,
            ["Operating Income"],
            latest_period
        )

        net_income = get_statement_value(
            statement,
            ["Net Income", "Net Income Common Stockholders"],
            latest_period
        )

        diluted_eps = get_statement_value(
            statement,
            ["Diluted EPS", "Basic EPS"],
            latest_period
        )

        revenue_growth = calculate_growth(revenue, previous_revenue)
        gross_margin = calculate_margin(gross_profit, revenue)
        operating_margin = calculate_margin(operating_income, revenue)
        net_margin = calculate_margin(net_income, revenue)

        return {
            "found": True,
            "ticker": symbol,
            "company_name": info.get("shortName") or info.get("longName") or symbol,
            "period_type": period_type,
            "latest_period": str(latest_period.date()) if hasattr(latest_period, "date") else str(latest_period),
            "revenue": revenue,
            "previous_revenue": previous_revenue,
            "revenue_growth": revenue_growth,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "net_income": net_income,
            "diluted_eps": diluted_eps,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "dividend_yield": info.get("dividendYield"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector") or "N/A",
            "industry": info.get("industry") or "N/A",
        }

    except Exception as error:
        return {
            "found": False,
            "ticker": ticker.upper(),
            "error": str(error)
        }


def summarize_earnings(data):
    prompt = f"""
You are the Earnings Analyst for Smart Money AI.

Summarize this company's latest earnings data in plain English.

Ticker: {data['ticker']}
Company: {data['company_name']}
Period Type: {data['period_type']}
Latest Period: {data['latest_period']}
Sector: {data['sector']}
Industry: {data['industry']}

Revenue: {format_number(data['revenue'])}
Previous Revenue: {format_number(data['previous_revenue'])}
Revenue Growth: {format_percent(data['revenue_growth'])}
Gross Profit: {format_number(data['gross_profit'])}
Operating Income: {format_number(data['operating_income'])}
Net Income: {format_number(data['net_income'])}
Diluted EPS: {data['diluted_eps'] if data['diluted_eps'] else 'N/A'}
Gross Margin: {format_percent(data['gross_margin'])}
Operating Margin: {format_percent(data['operating_margin'])}
Net Margin: {format_percent(data['net_margin'])}
P/E Ratio: {data['pe_ratio'] if data['pe_ratio'] else 'N/A'}
Forward P/E: {data['forward_pe'] if data['forward_pe'] else 'N/A'}
Dividend Yield: {format_percent(data['dividend_yield'])}
Market Cap: {format_number(data['market_cap'])}

Return a concise investor-friendly summary with:

1. Earnings trend
2. Profitability
3. Valuation
4. Dividend relevance, if any
5. Smart Money AI takeaway

Maximum 180 words.
End with: "This is research, not financial advice."
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    return response.output_text