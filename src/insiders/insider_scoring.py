from src.insiders.insider_data import get_insider_trades


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


ROLE_WEIGHTS = {
    "CEO": 14,
    "CFO": 12,
    "COO": 10,
    "PRESIDENT": 10,
    "DIRECTOR": 7,
    "CHAIRMAN": 8,
    "10% OWNER": 8,
    "OFFICER": 6,
}


AMOUNT_WEIGHTS = [
    ("$10M", 25),
    ("$5M", 22),
    ("$2M", 18),
    ("$1M", 15),
    ("$500K", 10),
    ("$250K", 7),
    ("$100K", 5),
    ("$50K", 3),
]


def clamp_score(score):
    return max(MIN_SCORE, min(MAX_SCORE, round(score)))


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip().upper()


def get_trade_ticker(trade):
    return clean_text(trade.get("ticker"))


def is_purchase(transaction):
    text = clean_text(transaction)

    return any(keyword.upper() in text for keyword in PURCHASE_KEYWORDS)


def is_sale(transaction):
    text = clean_text(transaction)

    return any(keyword.upper() in text for keyword in SALE_KEYWORDS)


def get_role_weight(insider_role):
    role = clean_text(insider_role)

    for keyword, weight in ROLE_WEIGHTS.items():
        if keyword in role:
            return weight

    return 4


def get_amount_weight(amount_range):
    amount_text = clean_text(amount_range)

    for keyword, weight in AMOUNT_WEIGHTS:
        if keyword in amount_text:
            return weight

    return 2


def score_trade(trade):
    transaction = trade.get("transaction", "")
    insider_role = trade.get("insider", "")
    amount_range = trade.get("amount_range", "")

    role_weight = get_role_weight(insider_role)
    amount_weight = get_amount_weight(amount_range)

    trade_score = role_weight + amount_weight

    if is_purchase(transaction):
        return trade_score

    if is_sale(transaction):
        return -trade_score

    return 0


def get_matching_trades(ticker):
    clean_ticker = clean_text(ticker)

    try:
        trades = get_insider_trades()
    except Exception:
        trades = []

    return [
        trade
        for trade in trades
        if get_trade_ticker(trade) == clean_ticker
    ]


def get_insider_score(ticker):
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