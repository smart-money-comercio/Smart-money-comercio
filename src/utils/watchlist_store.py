import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"

DEFAULT_WATCHLIST = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
]


def ensure_watchlist_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not WATCHLIST_FILE.exists():
        save_watchlist(DEFAULT_WATCHLIST)


def load_watchlist() -> list[str]:
    ensure_watchlist_file()

    try:
        with WATCHLIST_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        symbols = data.get("symbols", [])

        if not isinstance(symbols, list):
            return DEFAULT_WATCHLIST.copy()

        cleaned_symbols = []

        for symbol in symbols:
            if isinstance(symbol, str):
                cleaned = symbol.strip().upper()
                if cleaned and cleaned not in cleaned_symbols:
                    cleaned_symbols.append(cleaned)

        return cleaned_symbols

    except Exception:
        return DEFAULT_WATCHLIST.copy()


def save_watchlist(symbols: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cleaned_symbols = []

    for symbol in symbols:
        cleaned = symbol.strip().upper()

        if cleaned and cleaned not in cleaned_symbols:
            cleaned_symbols.append(cleaned)

    payload = {
        "symbols": cleaned_symbols
    }

    with WATCHLIST_FILE.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def add_symbols(symbols_to_add: list[str]) -> tuple[list[str], list[str]]:
    watchlist = load_watchlist()
    added = []

    for symbol in symbols_to_add:
        cleaned = symbol.strip().upper()

        if cleaned and cleaned not in watchlist:
            watchlist.append(cleaned)
            added.append(cleaned)

    save_watchlist(watchlist)

    return watchlist, added


def remove_symbols(symbols_to_remove: list[str]) -> tuple[list[str], list[str]]:
    watchlist = load_watchlist()
    removed = []

    symbols_to_remove_cleaned = {
        symbol.strip().upper()
        for symbol in symbols_to_remove
        if symbol.strip()
    }

    new_watchlist = []

    for symbol in watchlist:
        if symbol in symbols_to_remove_cleaned:
            removed.append(symbol)
        else:
            new_watchlist.append(symbol)

    save_watchlist(new_watchlist)

    return new_watchlist, removed


def clear_watchlist() -> None:
    save_watchlist([])


def reset_watchlist() -> list[str]:
    save_watchlist(DEFAULT_WATCHLIST)
    return DEFAULT_WATCHLIST.copy()


def get_watchlist_file_path() -> str:
    return str(WATCHLIST_FILE)