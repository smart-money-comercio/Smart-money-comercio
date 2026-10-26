"""Dated market sentiment and conditional implications from admitted evidence."""

from datetime import datetime
import re


MIN_MARKET_WORDS = 45
MAX_MARKET_WORDS = 90
PREFERRED_MARKET_WORDS = 75
DEFENSE_SYMBOLS = {"PLTR", "AVAV", "KTOS", "CRWD", "NOC", "LMT", "RTX", "GD", "HII", "CACI", "ITA"}


def word_count(text: str) -> int:
    text = re.sub(r"https?://\S+|/[A-Za-z][A-Za-z0-9_]*", "", text)
    return len(re.findall(r"\b[^\W_]+(?:['’\-][^\W_]+)*\b", text))


def story_topics(story: dict) -> set[str]:
    """Topic labels classify evidence; they do not establish a market cause."""
    title = story["title"]
    topics = set()
    if set(story.get("symbols", [])) & DEFENSE_SYMBOLS or story.get("source") == "DARPA" or re.search(r"\b(defen[cs]e|military|missile|counter.drone|drones?|munitions?|hypersonic|battlefield)\b", title, re.I):
        topics.add("defense")
    if re.search(r"\b(innovations?|introduces?|launch(?:es)?|unveils?|prototype|demonstrat\w*|flight test|autonomous|quantum|new .{0,25}(?:chip|platform|system))\b", title, re.I):
        topics.add("innovation")
    if re.search(r"\b(export (?:ban|restrictions?|controls?)|sanctions?|tariffs?|trade restrictions?)\b", title, re.I):
        topics.add("trade")
    if re.search(r"\b(chips?|semiconductors?|AI accelerators?)\b", title, re.I):
        topics.add("chips")
    security_title = re.sub(r"(?:Department|Secretary) of War", "defense authority", title, flags=re.I)
    if re.search(r"\b(conflict|escalation|war|air strikes?|military strikes?|missile strikes?|shipping|blockade)\b", security_title, re.I):
        topics.add("geopolitics")
    if re.search(r"\b(FOMC|interest rates?|monetary policy|policy rates?)\b", title, re.I):
        topics.add("policy")
    if re.search(r"\b(oil|crude|petroleum|energy|gasoline)\b", title, re.I):
        topics.add("energy")
    return topics


def sentiment(moves: dict) -> str:
    if not all(key in moves for key in ("S&P", "Nasdaq", "Russell")):
        return "limited by incomplete coverage"
    values = [moves[key] for key in ("S&P", "Nasdaq", "Russell")]
    if moves["Nasdaq"] <= -2 or sum(value < 0 for value in values) >= 2:
        return "cautious"
    if all(value > 0 for value in values) and moves.get("VIX", 0) <= 0:
        return "constructive"
    return "mixed"


def portfolio_lens(moves: dict, topics: set[str], mood: str) -> str:
    if "trade" in topics:
        return ("Verified trade-policy news puts chip-market access and supply chains on watch; check company guidance before changing exposure." if "chips" in topics else
                "Verified trade-policy news warrants checking cross-border costs and supply chains against company guidance before changing exposure.")
    if "geopolitics" in topics:
        return "Verified geopolitical news warrants reviewing energy and shipping costs alongside defense exposure; check funded demand and execution risk."
    if "policy" in topics:
        return "Verified policy news warrants checking financing costs and growth-company valuations alongside current price and volume."
    if "energy" in topics or moves.get("Oil", 0) >= 1.5:
        return "Higher energy costs could squeeze margins; review growth exposure and businesses sensitive to fuel costs."
    if mood == "cautious":
        return "Review concentrated growth exposure and upcoming catalysts; stronger price and volume confirmation would improve the research case."
    if mood == "constructive":
        return "Improving index support may help growth exposure; watch whether company participation and volume support the move."
    return "Check sector exposure and upcoming catalysts; broad signals alone do not settle the entry conditions for individual companies."


def market_segment(evidence: dict) -> str:
    moves = evidence["moves"]
    if not moves or not evidence["session"]:
        return ("A dated broad-market snapshot is unavailable, so an overall sentiment call would be premature. "
                "Portfolio lens: keep the research ranking separate from entry timing. Confirm the major indexes, volatility and current company prices before increasing conviction, and review upcoming policy and earnings releases for a clearer risk picture.")
    topics = set().union(*(story_topics(story) for story in evidence.get("stories", [])))
    mood = sentiment(moves)
    day = datetime.strptime(evidence["session"], "%Y-%m-%d").strftime("%A, %B %d")
    clock = f"During the {day} regular session" if evidence["is_open"] else f"At the {day} regular-session close"

    def move(key, label):
        value = moves[key]
        return f"{label} was unchanged" if value == 0 else f"{label} {'rose' if value > 0 else 'fell'} {abs(value):.2f} percent"

    indices = [(key, label) for key, label in (("S&P", "the S&P 500"), ("Nasdaq", "the Nasdaq Composite"), ("Russell", "the Russell 2000")) if key in moves]
    others = [(key, label) for key, label in (("VIX", "VIX"), ("Oil", "oil"), ("TLT", "the TLT bond fund")) if key in moves]

    def render():
        figures = "; ".join(move(key, label) for key, label in indices + others)
        qualification = " TLT tracks bond prices; yields are unverified." if any(key == "TLT" for key, _ in others) else ""
        return f"Our indicator-based sentiment read is {mood}. {clock}, {figures}.{qualification} Portfolio lens: " + portfolio_lens(moves, topics, mood)

    text = render()
    for key in ("Russell", "TLT", "Oil", "VIX"):
        if word_count(text) <= PREFERRED_MARKET_WORDS:
            break
        indices = [(k, v) for k, v in indices if k != key]
        others = [(k, v) for k, v in others if k != key]
        text = render()
    if word_count(text) < MIN_MARKET_WORDS:
        text += " These observations describe the quoted session; the next opening may present a different pattern."
    if not MIN_MARKET_WORDS <= word_count(text) <= MAX_MARKET_WORDS:
        raise ValueError("Market segment cannot satisfy its 15–30 second narration budget")
    return text


def defense_segment(stories: list[dict]) -> str:
    defense = [story for story in stories if "defense" in story_topics(story)]
    if defense:
        if any(re.search(r"\b(prototype|demonstrat\w*|tests?|concept)\b", story["title"], re.I) for story in defense):
            return ("Defense and innovation lens: Technical milestones warrant checking production readiness, funded demand and execution costs. "
                    "A prototype or demonstration alone does not establish orders or revenue; those are the next tests for defense exposure.")
        return ("Defense portfolio lens: Check funded commitments, procurement approvals and delivery timing behind these reports. "
                "Contract ceilings and geopolitical attention alone do not establish near-term revenue, margins or investment returns.")
    return ("Defense and innovation remain on our research watch, including drones, counter-drone systems, cybersecurity and autonomy. "
            "No current verified defense development qualified in this edition; check funded orders and production milestones before changing the industry outlook.")
