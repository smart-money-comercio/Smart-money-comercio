import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


FORECAST_HTML = """
<html>
<head>
<title>NVDA Forecast — StockAnalysis</title>
<meta name="description" content='According to 61 analysts, the average rating for NVDA stock is "Strong Buy". The 12-month stock price target is $302.83, which is an increase of 56.03% from the latest price.'>
</head>
<body>
<h1>NVIDIA Stock Forecast</h1>
<p>According to 61 analysts, the average rating for NVDA stock is "Strong Buy".</p>
<p>The 12-month stock price target is $302.83, which is an increase of 56.03% from the latest price.</p>
<table>
<tr><th>Rating</th><th>Current</th></tr>
<tr><td>Strong Buy</td><td>52</td></tr>
<tr><td>Buy</td><td>8</td></tr>
<tr><td>Hold</td><td>1</td></tr>
<tr><td>Sell</td><td>0</td></tr>
<tr><td>Strong Sell</td><td>0</td></tr>
<tr><td>Total</td><td>61</td></tr>
</table>
</body>
</html>
"""


STATISTICS_HTML = """
<html>
<head>
<title>NVDA Statistics — StockAnalysis</title>
</head>
<body>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Market Cap</td><td>4.25T</td></tr>
<tr><td>PE Ratio</td><td>55.20</td></tr>
<tr><td>Forward PE</td><td>38.75</td></tr>
<tr><td>Price/Sales</td><td>31.10</td></tr>
<tr><td>Price/Book</td><td>48.80</td></tr>
</table>
</body>
</html>
"""


FINANCIALS_HTML = """
<html>
<head>
<title>NVDA Financials — StockAnalysis</title>
</head>
<body>
<table>
<tr><th>Metric</th><th>TTM</th></tr>
<tr><td>Revenue</td><td>130.50B</td></tr>
<tr><td>Gross Profit</td><td>97.80B</td></tr>
<tr><td>Operating Income</td><td>82.20B</td></tr>
<tr><td>Net Income</td><td>72.90B</td></tr>
<tr><td>EPS Diluted</td><td>2.94</td></tr>
</table>
</body>
</html>
"""


BALANCE_SHEET_HTML = """
<html>
<head>
<title>NVDA Balance Sheet — StockAnalysis</title>
</head>
<body>
<table>
<tr><th>Metric</th><th>Latest</th></tr>
<tr><td>Cash and Cash Equivalents</td><td>43.20B</td></tr>
<tr><td>Total Debt</td><td>10.90B</td></tr>
<tr><td>Total Assets</td><td>111.60B</td></tr>
<tr><td>Total Liabilities</td><td>32.30B</td></tr>
<tr><td>Total Shareholders' Equity</td><td>79.30B</td></tr>
</table>
</body>
</html>
"""


CASH_FLOW_HTML = """
<html>
<head>
<title>NVDA Cash Flow — StockAnalysis</title>
</head>
<body>
<table>
<tr><th>Metric</th><th>TTM</th></tr>
<tr><td>Operating Cash Flow</td><td>76.40B</td></tr>
<tr><td>Free Cash Flow</td><td>72.10B</td></tr>
<tr><td>Capital Expenditures</td><td>-4.30B</td></tr>
</table>
</body>
</html>
"""


OVERVIEW_HTML = """
<html>
<head>
<title>NVIDIA Corporation Overview — StockAnalysis</title>
<meta name="description" content="NVIDIA Corporation stock overview, quote, financials, forecast and analyst ratings.">
</head>
<body>
<h1>NVIDIA Corporation</h1>
</body>
</html>
"""


FIXTURE_HTML_BY_PAGE = {
    "overview": OVERVIEW_HTML,
    "forecast": FORECAST_HTML,
    "statistics": STATISTICS_HTML,
    "financials": FINANCIALS_HTML,
    "balance_sheet": BALANCE_SHEET_HTML,
    "cash_flow": CASH_FLOW_HTML,
}


def fake_fetch_page(symbol: str, page: str, force_refresh: bool = False) -> dict:
    html = FIXTURE_HTML_BY_PAGE.get(page, OVERVIEW_HTML)

    return {
        "symbol": str(symbol or "").upper(),
        "page": page,
        "url": f"fixture://stockanalysis/{symbol}/{page}",
        "fetched_at": "2026-08-18 00:00:00",
        "fetched_at_epoch": time.time(),
        "cache_hit": False,
        "status": "ok",
        "html": html,
    }


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        import src.intelligence.stockanalysis_source as source
    except Exception as error:
        print("StockAnalysis Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Import failed: {type(error).__name__}: {error}")
        return 1

    # Network-safe monkeypatch. This prevents preflight from depending on
    # StockAnalysis.com availability, throttling, HTML delivery, or network access.
    source.fetch_page = fake_fetch_page

    try:
        data = source.fetch_stockanalysis_data("NVDA", force_refresh=True)
        metrics = data.get("metrics", {})
    except Exception as error:
        print("StockAnalysis Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Parser failed: {type(error).__name__}: {error}")
        return 1

    require(data.get("available") is True, "StockAnalysis data should be available", errors)
    require(metrics.get("analyst_consensus") == "Strong Buy", "analyst_consensus should parse Strong Buy", errors)
    require(metrics.get("price_target") == "$302.83", "price_target should parse $302.83", errors)
    require(metrics.get("price_target_upside") == "56.03%", "price_target_upside should parse 56.03%", errors)
    require(metrics.get("strong_buy_count") == "52", "strong_buy_count should parse 52", errors)
    require(metrics.get("buy_count") == "8", "buy_count should parse 8", errors)
    require(metrics.get("hold_count") == "1", "hold_count should parse 1", errors)
    require(metrics.get("sell_count") == "0", "sell_count should parse 0", errors)
    require(metrics.get("strong_sell_count") == "0", "strong_sell_count should parse 0", errors)
    require(metrics.get("analyst_total") == "61", "analyst_total should parse 61", errors)

    require(metrics.get("market_cap") == "4.25T", "market_cap should parse 4.25T", errors)
    require(metrics.get("revenue") == "130.50B", "revenue should parse 130.50B", errors)
    require(metrics.get("free_cash_flow") == "72.10B", "free_cash_flow should parse 72.10B", errors)
    require(metrics.get("total_debt") == "10.90B", "total_debt should parse 10.90B", errors)

    try:
        rating_section = source.build_stockanalysis_rating_section("NVDA", force_refresh=True)
    except Exception as error:
        rating_section = ""
        errors.append(f"build_stockanalysis_rating_section failed: {type(error).__name__}: {error}")

    require("External Analyst Consensus" in rating_section, "rating section missing External Analyst Consensus", errors)
    require("Consensus: Strong Buy" in rating_section, "rating section missing Strong Buy consensus", errors)
    require("Price Target: $302.83" in rating_section, "rating section missing price target", errors)
    require("Strong Buy: 52" in rating_section, "rating section missing Strong Buy count", errors)

    try:
        snapshot = source.build_stockanalysis_snapshot("NVDA", force_refresh=True)
    except Exception as error:
        snapshot = ""
        errors.append(f"build_stockanalysis_snapshot failed: {type(error).__name__}: {error}")

    require("StockAnalysis Snapshot: NVDA" in snapshot, "snapshot missing header", errors)
    require("Market Cap: 4.25T" in snapshot, "snapshot missing Market Cap", errors)
    require("Revenue: 130.50B" in snapshot, "snapshot missing Revenue", errors)
    require("Free Cash Flow: 72.10B" in snapshot, "snapshot missing Free Cash Flow", errors)

    try:
        import src.reports.analyst_stockanalysis_bridge as bridge

        bridge.fetch_stockanalysis_data = source.fetch_stockanalysis_data
        overlay = bridge.build_stockanalysis_analyst_overlay("NVDA", force_refresh=True)
    except Exception as error:
        overlay = ""
        errors.append(f"build_stockanalysis_analyst_overlay failed: {type(error).__name__}: {error}")

    require("StockAnalysis Analyst Overlay: NVDA" in overlay, "overlay missing header", errors)
    require("Consensus: Strong Buy" in overlay, "overlay missing Strong Buy consensus", errors)
    require("Rating Bucket: Strong Buy" in overlay, "overlay missing Strong Buy rating bucket", errors)

    try:
        import src.reports.stockanalysis_data_report as data_report

        data_report.fetch_stockanalysis_data = source.fetch_stockanalysis_data
        report = data_report.build_stockanalysis_data_report("NVDA", force_refresh=True)
    except Exception as error:
        report = ""
        errors.append(f"build_stockanalysis_data_report failed: {type(error).__name__}: {error}")

    require("StockAnalysis Data: NVDA" in report, "stockdata report missing header", errors)
    require("Consensus: Strong Buy" in report, "stockdata report missing Strong Buy consensus", errors)
    require("StockAnalysis Snapshot: NVDA" in report, "stockdata report missing snapshot", errors)

    print("StockAnalysis Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Metrics Parsed: {len(metrics)}")
    print(f"Consensus: {metrics.get('analyst_consensus', 'missing')}")
    print(f"Price Target: {metrics.get('price_target', 'missing')}")
    print(f"Upside: {metrics.get('price_target_upside', 'missing')}")
    print(f"Analyst Total: {metrics.get('analyst_total', 'missing')}")

    if errors:
        print("")
        print("Errors:")

        for error in errors:
            print(f"- {error}")

        return 1

    print("")
    print("StockAnalysis parser and report integrations are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())