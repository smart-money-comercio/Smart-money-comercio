import requests

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"


def fetch_json(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def normalize_trade(trade, source):
    politician = (
        trade.get("representative")
        or trade.get("senator")
        or trade.get("name")
        or "Unknown"
    )

    ticker = (
        trade.get("ticker")
        or trade.get("asset_ticker")
        or ""
    )

    return {
        "politician": politician,
        "ticker": ticker.strip().upper(),
        "transaction": trade.get("type") or trade.get("transaction_type") or "Unknown",
        "sector": "Unknown",
        "amount_range": trade.get("amount") or trade.get("amount_range") or "Unknown",
        "disclosure_date": trade.get("disclosure_date") or trade.get("date") or "Unknown",
        "source": source,
    }


def get_real_congress_trades(limit=25):
    trades = []

    for url, source in [
        (HOUSE_URL, "House"),
        (SENATE_URL, "Senate"),
    ]:
        try:
            data = fetch_json(url)

            for trade in data:
                normalized = normalize_trade(trade, source)

                if (
                    normalized["ticker"]
                    and normalized["ticker"] != "--"
                    and normalized["transaction"] != "Unknown"
                ):
                    trades.append(normalized)

                if len(trades) >= limit:
                    return trades

        except Exception as error:
            print(f"{source} data error: {error}")

    return trades