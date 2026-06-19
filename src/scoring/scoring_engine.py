from src.scoring.watchlist import WATCHLIST

def get_stock_scores():

    stocks = WATCHLIST.copy()

    for stock in stocks:
        stock["final_score"] = round(
            (stock["smart_score"] * 0.7)
            + (stock["defense_score"] * 0.3)
        )

    return sorted(
        stocks,
        key=lambda x: x["final_score"],
        reverse=True
    )