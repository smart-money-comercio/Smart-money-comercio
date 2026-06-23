from src.congress.congress_data import CONGRESS_TRADES


def get_congress_trades():
    return CONGRESS_TRADES


def get_congress_score(ticker):
    score = 0

    for trade in CONGRESS_TRADES:
        if trade["ticker"].upper() == ticker.upper():
            if trade["transaction"] == "Purchase":
                score += 15
            elif trade["transaction"] == "Sale":
                score -= 10

            if "$1M" in trade["amount_range"] or "$5M" in trade["amount_range"]:
                score += 10

    return max(score, 0)


def get_top_congress_buys():
    return [
        trade for trade in CONGRESS_TRADES
        if trade["transaction"] == "Purchase"
    ]