from src.insiders.insider_data import INSIDER_TRADES


def get_insider_trades():
    return INSIDER_TRADES


def get_insider_score(ticker):
    score = 0

    for trade in INSIDER_TRADES:
        if trade["ticker"].upper() == ticker.upper():
            if trade["transaction"] == "Purchase":
                score += 15

            if trade["insider"] == "CEO":
                score += 10

            if trade["insider"] == "CFO":
                score += 7

            if "$500K" in trade["amount_range"] or "$1M" in trade["amount_range"]:
                score += 5

    return max(score, 0)