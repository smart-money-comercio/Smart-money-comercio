"""Dated market sentiment and conditional implications from admitted evidence."""

from datetime import datetime
import re


MIN_MARKET_WORDS = 45
MAX_MARKET_WORDS = 90
PREFERRED_MARKET_WORDS = 75
DEFENSE_SYMBOLS = {"PLTR", "AVAV", "KTOS", "CRWD", "NOC", "LMT", "RTX", "GD", "HII", "CACI", "ITA"}
MARKET_CONTEXT_TOPICS = {"trade", "export restrictions", "import tariffs", "geopolitics", "policy", "energy", "IPO", "AI financing"}

EXPORT_MEASURE = r"export (?:bans?|restrictions?|controls?)"
TARIFF_MEASURE = r"(?:tariffs?|import duties)"
TRADE_OR_SANCTIONS = re.compile(r"\b(?:" + EXPORT_MEASURE + "|" + TARIFF_MEASURE + r"|trade restrictions?|sanction(?:s|ed|ing)?|OFAC)\b", re.I)
TRADE_ACTION = (r"\b(?:announc(?:ed|es)|impos(?:ed|es)|introduc(?:ed|es)|issu(?:ed|es)|adopt(?:ed|s)|"
                r"enact(?:ed|s)|expand(?:ed|s)|rais(?:ed|es)|lower(?:ed|s)|implement(?:ed|s)|sets?) "
                r"(?:a |an |the |its )?(?:(?:new|additional|revised|higher|lower|\d+(?:\.\d+)?(?:%| percent)) ){0,3}")
TRADE_GOODS = (r"(?:(?:advanced|AI|high[- ]performance|imported|finished|electric|passenger|primary) ){0,3}"
               r"(?:chips?|semiconductors?|AI accelerators?|steel|alumin(?:um|ium)|vehicles?|batteries|solar (?:panels?|cells?)|"
               r"crude oil|petroleum products?|critical minerals?|copper|lithium)\b")


def word_count(text: str) -> int:
    text = re.sub(r"https?://\S+|/[A-Za-z][A-Za-z0-9_]*", "", text)
    return len(re.findall(r"\b[^\W_]+(?:['’\-][^\W_]+)*\b", text))


def story_topics(story: dict) -> set[str]:
    """Topic labels classify evidence; they do not establish a market cause."""
    title = story["title"]
    topics = set()
    if story.get("ipo"):
        topics.add("IPO")
    if story.get("sec_filing", {}).get("disclosure", {}).get("gpu_lease"):
        topics.add("AI financing")
    if set(story.get("symbols", [])) & DEFENSE_SYMBOLS or story.get("source") == "DARPA" or re.search(r"\b(defen[cs]e|military|missile|counter.drone|drones?|munitions?|hypersonic|battlefield)\b", title, re.I):
        topics.add("defense")
    if re.search(r"\b(innovations?|introduces?|launch(?:es)?|unveils?|prototype|demonstrat\w*|flight test|autonomous|quantum|new .{0,25}(?:chip|platform|system))\b", title, re.I):
        topics.add("innovation")
    financial = story.get("event_evidence", {}).get("schema") == 13
    if financial:
        topics.add("financial sanctions")
    if re.search(r"\b(export (?:ban|restrictions?|controls?)|" + ("" if financial else "sanctions?|") + r"tariffs?|trade restrictions?)\b", title, re.I):
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


def market_story_topics(story: dict, *, business_version: int) -> set[str]:
    """Use a release's actual trade measure and covered goods for the market read."""
    topics = story_topics(story)
    if business_version < 8:
        return topics
    title = story["title"]
    if not TRADE_OR_SANCTIONS.search(title) and "financial sanctions" not in topics:
        return topics - {"chips"}
    # Words such as oil or shipping can describe who was sanctioned, without
    # establishing a new restriction on the product or industry.
    topics -= {"trade", "chips", "financial sanctions", "geopolitics", "policy", "energy"}
    profile = story.get("event_evidence", {})
    if profile.get("scope") != "original release excerpt":
        return topics
    from src.intelligence.original_disclosures import UNCONFIRMED, sentences
    qualified = UNCONFIRMED + r'|\b(?:if|unless|never|earlier|last year|propos\w*|consider\w*|plans?|recommend\w*|pending)\b|["“”]'
    rows = [row for row in sentences(profile.get("source_text", "")) if not re.search(qualified, row, re.I)]
    for topic, measure in (("export restrictions", EXPORT_MEASURE), ("import tariffs", TARIFF_MEASURE)):
        action = TRADE_ACTION + measure + r" (?:on|covering) " + TRADE_GOODS
        if re.search(r"\b" + measure + r"\b", title, re.I) and any(re.search(action, row, re.I) for row in rows):
            topics.add(topic)
    return topics


def market_topics(evidence: dict) -> set[str]:
    version = evidence.get("business_version", 0)
    return set().union(*(market_story_topics(story, business_version=version) for story in evidence.get("stories", [])))


def sentiment(moves: dict, *, pressure_first=False) -> str:
    if pressure_first:
        from src.intelligence.market_priority import sharp_loss
        if sharp_loss(moves):
            return "cautious"
    if not all(key in moves for key in ("S&P", "Nasdaq", "Russell")):
        return "limited by incomplete coverage"
    values = [moves[key] for key in ("S&P", "Nasdaq", "Russell")]
    if moves["Nasdaq"] <= -2 or sum(value < 0 for value in values) >= 2:
        return "cautious"
    if all(value > 0 for value in values) and moves.get("VIX", 0) <= 0:
        return "constructive"
    return "mixed"


def portfolio_lens(moves: dict, topics: set[str], mood: str, *, pressure_first=False) -> str:
    if pressure_first:
        from src.intelligence.market_priority import sharp_loss
        if sharp_loss(moves):
            return "Review concentrated growth exposure and upcoming company results; watch whether selling eases and participation improves before increasing conviction."
    if "export restrictions" in topics:
        return "Watch whether export restrictions change shipments or revenue guidance for suppliers of the covered goods."
    if "import tariffs" in topics:
        return "For importers of the covered goods, watch whether the tariff change shows up in costs, prices or margins."
    if "trade" in topics:
        return ("Verified trade-policy news puts chip-market access and supply chains on watch; check company guidance before changing exposure." if "chips" in topics else
                "Verified trade-policy news warrants checking cross-border costs and supply chains against company guidance before changing exposure.")
    if "geopolitics" in topics:
        return "Verified geopolitical news warrants reviewing energy and shipping costs alongside defense exposure; check funded demand and execution risk."
    if "policy" in topics:
        return "Verified policy news warrants checking financing costs and growth-company valuations alongside current price and volume."
    if "energy" in topics or moves.get("Oil", 0) >= 1.5:
        return "Higher energy costs could squeeze margins; review growth exposure and businesses sensitive to fuel costs."
    if "financial sanctions" in topics:
        return "Targeted financial sanctions call for checking payment and counterparty exposure. Company disclosures are needed to assess any effect on sales or costs."
    if "IPO" in topics:
        return "AI IPO news adds a valuation comparison; review capital needs and AI exposure. A filing alone does not establish tradable shares."
    if "AI financing" in topics:
        return "AI infrastructure financing warrants checking funding costs, delivery conditions and capital commitments; announced plans do not establish completed deployments."
    if mood == "cautious":
        return "Review concentrated growth exposure and upcoming catalysts; stronger price and volume confirmation would improve the research case."
    if mood == "constructive":
        return "Improving index support may help growth exposure; watch whether company participation and volume support the move."
    return "Check sector exposure and upcoming catalysts; broad signals alone do not settle the entry conditions for individual companies."


def rally_leadership(evidence: dict) -> str:
    """Compare dated index gains when the difference is large enough to discuss."""
    if evidence.get("business_version", 0) < 6 or not evidence.get("session"):
        return ""
    moves = evidence["moves"]
    if sentiment(moves) != "constructive" or abs(moves.get("Oil", 0)) >= 1.5 or abs(moves.get("TLT", 0)) >= 0.5:
        return ""
    if market_topics(evidence) & (MARKET_CONTEXT_TOPICS | {"financial sanctions"}):
        return ""
    leader, middle, laggard = sorted(("S&P", "Nasdaq", "Russell"), key=moves.__getitem__, reverse=True)
    if round(moves[leader] - moves[laggard], 2) < 0.50:
        return ""
    labels = {"S&P": "S&P 500", "Nasdaq": "Nasdaq Composite", "Russell": "small-cap Russell 2000"}
    day = datetime.strptime(evidence["session"], "%Y-%m-%d").strftime("%A")
    opened = evidence["is_open"]
    clock = f"During the {day} session" if opened else f"At {day}'s close"
    horizon = "through the close" if opened else "in the next session"
    lagging_market = "small caps" if laggard == "Russell" else f"the {labels[laggard]}"
    volatility = ("A dated VIX reading was unavailable." if "VIX" not in moves else
                  f"The VIX fell {abs(moves['VIX']):.2f} percent." if moves["VIX"] < 0 else "The VIX was unchanged.")
    text = (f"{clock}, the {labels[leader]} rose {moves[leader]:.2f} percent, leading the three indexes we track. "
            f"The {labels[middle]} rose {moves[middle]:.2f} percent and the {labels[laggard]} gained {moves[laggard]:.2f} percent. "
            f"{volatility} Watch whether {lagging_market} can narrow the gap {horizon}.")
    from src.utils.speech_text import normalize, words
    return text if word_count(text) >= MIN_MARKET_WORDS and words(normalize(text)) <= PREFERRED_MARKET_WORDS else ""


def market_segment(evidence: dict) -> str:
    leadership = rally_leadership(evidence)
    if leadership:
        return leadership
    moves = evidence["moves"]
    if not moves or not evidence["session"]:
        return ("A dated broad-market snapshot is unavailable, so an overall sentiment call would be premature. "
                "Portfolio lens: keep the research ranking separate from entry timing. Confirm the major indexes, volatility and current company prices before increasing conviction, and review upcoming policy and earnings releases for a clearer risk picture.")
    topics = market_topics(evidence)
    pressure_first = evidence.get("reader_version") == 4
    mood = sentiment(moves, pressure_first=pressure_first)
    from src.intelligence.market_priority import selloff
    pressure = pressure_first and selloff(evidence)
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
        basis = " based on available indexes; coverage is incomplete" if pressure and not all(key in moves for key in ("S&P","Nasdaq","Russell")) else ""
        return f"Our indicator-based sentiment read is {mood}{basis}. {clock}, {figures}.{qualification} Portfolio lens: " + portfolio_lens(moves, topics, mood, pressure_first=pressure_first)

    text = render()
    for key in (("TLT", "Oil", "Russell", "VIX") if pressure else ("Russell", "TLT", "Oil", "VIX")):
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


def defense_segment(stories: list[dict], *, broadcast=False, business_version=0) -> str:
    defense = [story for story in stories if "defense" in story_topics(story)]
    if defense:
        companies = [story for story in defense if story.get("kind") == "company"]
        if companies:
            from src.agents.analyst_agent import review_sourced_development
            from src.intelligence.daily_brief_analysis import NAMES
            if business_version:
                from src.intelligence.business_analysis import compare, name
                from src.intelligence.broadcast_story import company_read
                comparison = compare(companies)
                if comparison:
                    watches = []
                    for story in companies:
                        watch = company_read(story, business_version=1)["watch"]
                        watches.append("For " + name(story) + ", " + watch[0].lower() + watch[1:])
                    return comparison["text"] + " " + " ".join(watches)
            parts = []
            for story in companies:
                review = review_sourced_development(story)
                symbol = story.get("publisher_symbol") or story["symbols"][0]
                if broadcast:
                    from src.intelligence.broadcast_story import company_read, next_check
                    review = company_read(story, business_version=business_version)
                    if business_version:
                        from src.intelligence.business_analysis import follow_through
                        parts.append(follow_through(story, review, concise=business_version >= 2))
                    else:
                        parts.append(f"Our view on {NAMES.get(symbol, symbol)}: " + review["why"] + " " + next_check(review["watch"]))
                else:
                    parts.append(f"For {NAMES.get(symbol, symbol)}, our analysis: " + review["why"] + " Watch next: " + review["watch"])
            if any(story.get("kind") != "company" and re.search(r"\b(prototype|demonstrat\w*|tests?|concept)\b", story["title"], re.I) for story in defense):
                parts.append("The agency's technical milestone still requires evidence of production readiness and funded demand.")
            return " ".join(parts)
        if any(re.search(r"\b(prototype|demonstrat\w*|tests?|concept)\b", story["title"], re.I) for story in defense):
            return ("Defense and innovation lens: Technical milestones warrant checking production readiness, funded demand and execution costs. "
                    "A prototype or demonstration alone does not establish orders or revenue; those are the next tests for defense exposure.")
        return ("Defense portfolio lens: Check funded commitments, procurement approvals and delivery timing behind these reports. "
                "Contract ceilings and geopolitical attention alone do not establish near-term revenue, margins or investment returns.")
    if business_version >= 7:
        return ("Today's defense coverage is limited. Funded orders and delivery schedules are the next business checks "
                "because they show how much work companies have secured and when it could contribute to sales.")
    if business_version >= 2:
        return "No current verified defense development qualified in this edition."
    return ("Defense and innovation remain on our research watch, including drones, counter-drone systems, cybersecurity and autonomy. "
            "No current verified defense development qualified in this edition; check funded orders and production milestones before changing the industry outlook.")
