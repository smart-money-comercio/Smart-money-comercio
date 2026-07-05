from src.congress.congress_data import get_congress_trades


MIN_SCORE = 0
MAX_SCORE = 100
NEUTRAL_SCORE = 50


PURCHASE_KEYWORDS = [
    "purchase",
    "buy",
    "acquisition",
    "acquired",
]

SALE_KEYWORDS = [
    "sale",
    "sell",
    "sold",
    "disposition",
]

AMOUNT_WEIGHTS = [
    ("$50,000,000", 35),
    ("$25,000,000", 32),
    ("$15,000,000", 30),
    ("$5,000,000", 26),
    ("$1,000,000", 22),
    ("$500,000", 16),
    ("$250,000", 12),
    ("$100,000", 9),
    ("$50,000", 6),
    ("$15,000", 3),
    ("$5M", 26),
    ("$1M", 22),
    ("$500K", 16),
    ("$250K", 12),
    ("$100K", 9),
    ("$50K", 6),
    ("$15K", 3),
]

COMMITTEE_RELEVANCE_WEIGHTS = {
    "HIGH": 10,
    "MEDIUM": 5,
    "LOW": 1,
    "UNKNOWN": 0,
}

SECTOR_RELEVANCE_WEIGHTS = {
    "AI": 6,
    "ARTIFICIAL INTELLIGENCE": 6,
    "SEMICONDUCTOR": 6,
    "DEFENSE": 6,
    "CYBER": 6,
    "CLOUD": 4,
    "AEROSPACE": 4,
    "MISSILE": 4,
    "GOVERNMENT": 4,
    "ENERGY": 3,
    "HEALTHCARE": 3,
    "PHARMA": 3,
    "BANK": 3,
    "FINANCIAL": 3,
}


def get_congress_trades_safe():
    try:
        return get_congress_trades()
    except Exception:
        return []


def clamp_score(score):
    return max(MIN_SCORE, min(MAX_SCORE, round(score)))


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip().upper()


def clean_ticker(value):
    return clean_text(value).replace("$", "")


def is_purchase(transaction):
    text = clean_text(transaction)

    return any(keyword.upper() in text for keyword in PURCHASE_KEYWORDS)


def is_sale(transaction):
    text = clean_text(transaction)

    return any(keyword.upper() in text for keyword in SALE_KEYWORDS)


def get_amount_weight(amount_range):
    amount_text = clean_text(amount_range)

    for keyword, weight in AMOUNT_WEIGHTS:
        if keyword in amount_text:
            return weight

    return 2


def get_committee_relevance_weight(value):
    relevance = clean_text(value)

    return COMMITTEE_RELEVANCE_WEIGHTS.get(relevance, 0)


def get_sector_relevance_weight(sector):
    sector_text = clean_text(sector)
    score = 0

    for keyword, weight in SECTOR_RELEVANCE_WEIGHTS.items():
        if keyword in sector_text:
            score += weight

    return min(score, 12)


def score_trade(trade):
    transaction = trade.get("transaction", "")
    amount_range = trade.get("amount_range", "")
    committee_relevance = trade.get("committee_relevance", "")
    sector = trade.get("sector", "")

    trade_score = (
        get_amount_weight(amount_range)
        + get_committee_relevance_weight(committee_relevance)
        + get_sector_relevance_weight(sector)
    )

    if is_purchase(transaction):
        return trade_score

    if is_sale(transaction):
        return -trade_score

    return 0


def get_matching_trades(ticker):
    clean = clean_ticker(ticker)
    trades = get_congress_trades_safe()

    return [
        trade
        for trade in trades
        if clean_ticker(trade.get("ticker")) == clean
    ]


def get_congress_score(ticker):
    matching_trades = get_matching_trades(ticker)

    if not matching_trades:
        return NEUTRAL_SCORE

    raw_score = NEUTRAL_SCORE
    purchase_count = 0
    sale_count = 0

    for trade in matching_trades:
        transaction = trade.get("transaction", "")

        if is_purchase(transaction):
            purchase_count += 1

        if is_sale(transaction):
            sale_count += 1

        raw_score += score_trade(trade)

    if purchase_count >= 3:
        raw_score += 8

    if sale_count >= 3:
        raw_score -= 8

    if purchase_count > sale_count:
        raw_score += 5

    if sale_count > purchase_count:
        raw_score -= 5

    return clamp_score(raw_score)


def get_top_congress_buys():
    return [
        trade
        for trade in get_congress_trades_safe()
        if is_purchase(trade.get("transaction"))
    ]


def get_top_congress_sells():
    return [
        trade
        for trade in get_congress_trades_safe()
        if is_sale(trade.get("transaction"))
    ]