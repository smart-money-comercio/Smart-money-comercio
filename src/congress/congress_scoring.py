from src.congress.congress_data import CONGRESS_TRADES


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
    ("$5M", 24),
    ("$1M", 20),
    ("$500K", 15),
    ("$250K", 11),
    ("$100K", 8),
    ("$50K", 5),
    ("$15K", 3),
]


COMMITTEE_RELEVANCE_WEIGHTS = {
    "HIGH": 10,
    "MEDIUM": 5,
    "LOW": 1,
}


SECTOR_RELEVANCE_WEIGHTS = {
    "AI": 6,
    "SEMICONDUCTOR": 6,
    "DEFENSE": 6,
    "CYBER": 6,
    "CLOUD": 4,
    "AEROSPACE": 4,
    "MISSILE": 4,
    "GOVERNMENT": 4,
    "ENERGY": 3,
    "DIVIDEND": 2,
}


POLITICIAN_WEIGHTS = {
    "NANCY PELOSI": 8,
    "RO KHANNA": 4,
    "TOMMY TUBERVILLE": 4,
    "JOSH GOTTHEIMER": 4,
    "MODEL AGGREGATE": 0,
}


def get_congress_trades():
    return CONGRESS_TRADES


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


def get_politician_weight(politician):
    name = clean_text(politician)

    return POLITICIAN_WEIGHTS.get(name, 1)


def score_trade(trade):
    transaction = trade.get("transaction", "")
    amount_range = trade.get("amount_range", "")
    committee_relevance = trade.get("committee_relevance", "")
    sector = trade.get("sector", "")
    politician = trade.get("politician", "")

    trade_score = (
        get_amount_weight(amount_range)
        + get_committee_relevance_weight(committee_relevance)
        + get_sector_relevance_weight(sector)
        + get_politician_weight(politician)
    )

    if is_purchase(transaction):
        return trade_score

    if is_sale(transaction):
        return -trade_score

    return 0


def get_matching_trades(ticker):
    clean = clean_ticker(ticker)

    return [
        trade
        for trade in CONGRESS_TRADES
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
        for trade in CONGRESS_TRADES
        if is_purchase(trade.get("transaction"))
    ]


def get_top_congress_sells():
    return [
        trade
        for trade in CONGRESS_TRADES
        if is_sale(trade.get("transaction"))
    ]