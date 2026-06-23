from src.scoring.scoring_engine import get_stock_scores

def get_stock(ticker):
    scores = get_stock_scores()

    for stock in scores:
        if stock["ticker"].upper() == ticker.upper():
            return stock

    return None