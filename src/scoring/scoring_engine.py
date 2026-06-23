from src.scoring.watchlist import WATCHLIST
from src.congress.congress_scoring import get_congress_score


def get_stock_scores():
    stocks = [stock.copy() for stock in WATCHLIST]

    for stock in stocks:
        congress_score = get_congress_score(stock["ticker"])

        stock["congress_score"] = congress_score

        stock["final_score"] = round(
            (stock["smart_score"] * 0.60)
            + (stock["defense_score"] * 0.25)
            + (congress_score * 0.15)
        )

    return sorted(
        stocks,
        key=lambda x: x["final_score"],
        reverse=True
    )