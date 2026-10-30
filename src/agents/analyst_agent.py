from typing import Any

from src.utils.score_display import (
    format_stock_label_block,
    get_action_label,
    get_portfolio_fit,
    get_risk_label as get_display_risk_label,
    get_score_story,
    get_signal_strength,
    get_smart_money_label,
)


DEFAULT_MAX_ITEMS = 5


def review_daily_brief(evidence: dict, *, presentation: str = "full") -> list[dict]:
    """Explain report facts and entry conditions without fetching or rescoring."""
    moves, breadth = evidence["moves"], evidence["breadth"]
    companies = evidence["companies"]
    insights = []

    def add(key, section, text, sources):
        insights.append({"id": key, "section": section, "text": text, "sources": sources})

    from src.intelligence.market_brief import market_segment, defense_segment
    add("market_pulse", "market", market_segment(evidence), ["Executive Summary", "Market Snapshot"]
        + (["Verified story decisions"] if evidence.get("stories") else []))
    broadcast = evidence.get("narration_version") == 2
    add("defense_watch", "global", defense_segment(evidence.get("stories", []), broadcast=broadcast),
        ["Verified story decisions"] if evidence.get("stories") else ["Research coverage policy"])
    if breadth:
        up, down, total = (breadth[key] for key in ("up", "down", "total"))
        scope = (f"Within the {total}-symbol research watchlist, {up} are higher and {down} lower." if evidence["is_open"] else
                 f"Within the {total}-symbol research watchlist, {up} finished higher and {down} lower.")
        if down > up and all(key in moves and moves[key] > 0 for key in ("S&P", "Nasdaq", "Russell")):
            scope += " Index gains are not shared by most names in this research watchlist."
        add("participation", "watch", scope, ["Market Snapshot"])
    if "company_focus" in evidence:
        from src.intelligence.company_focus import focus_paragraph, grouped_price_watch
        selected = evidence["company_focus"]["selected"]
        group = grouped_price_watch(evidence)
        group_added = False
        for index, row in enumerate(selected, 1):
            if group and row["symbol"] in group["symbols"]:
                if not group_added:
                    add("company_focus_moves", "company", group["text"], group["sources"] + ["Company focus selection"])
                    group_added = True
                continue
            text = focus_paragraph(row, evidence.get("stories", []))
            contexts = evidence.get("earnings_context", [])
            if contexts and row["symbol"] in {"GOOG", "GOOGL"}:
                from src.intelligence.alphabet_earnings import narration
                event = next(value for value in evidence["market_event_context"]["events"] if value["symbol"] in {"GOOG", "GOOGL"} and value["status"] == "rechecked")
                text = narration(contexts[0], event)
            if text:
                add(f"company_focus_{index}", "company", text, row["sources"] + ["Company focus selection"]
                    + (["Recent earnings context"] if contexts and row["symbol"] in {"GOOG", "GOOGL"} else []))
        if selected:
            confirmation = ("Our next check is whether company disclosures, price and volume support these research ideas. The full report has the rankings, risks and trade-plan conditions." if broadcast else
                            "For these companies, the next test is agreement between original disclosures, price and volume. Company selection reflects today's research relevance; the numerical rankings remain available in the full report.")
            add("focus_confirmation", "watch", confirmation,
                ["Company focus selection", "Market Snapshot"])
        companies = []
    if companies:
        top = companies[0]
        changed = evidence.get("leadership")
        if changed:
            introduction = f"{top['name']} moved ahead of {changed['previous_name']} in our research ranking, at {top['opportunity']:g} out of 100."
        else:
            introduction = f"{top['name']} leads our research ranking at {top['opportunity']:g} out of 100."
        if abs(top["opportunity"] - top["structural"]) >= 5:
            introduction += f" Its structural support score is {top['structural']:g}; the opportunity ranking also reflects shorter-term research inputs."
        if top["delta"]:
            introduction += f" Its opportunity score {'rose' if top['delta'] > 0 else 'fell'} {abs(top['delta']):g} points versus the prior report."
        if len(companies) > 1:
            introduction += f" {companies[1]['name']} follows at {companies[1]['opportunity']:g}."
        if len(companies) > 2:
            introduction += f" {companies[2]['name']} is third."
        introduction += " Research scores express priority rather than expected returns."
        add("ranking", "company", introduction, ["Top Opportunities"] + (["What Changed Today"] if changed else []))
        inputs = top.get("inputs")
        if inputs:
            labels = {"core": "core research", "theme": "the theme component", "congress": "the congressional activity score", "insiders": "the insider activity score"}
            supported = sorted((key for key, value in inputs.items() if value >= (65 if key in {"congress", "insiders"} else 75)),
                               key=lambda key: inputs[key], reverse=True)[:2]
            if supported:
                factors = " and ".join(labels[key] for key in supported)
                support = f"In our longer-term model, {top['name']} draws support from {factors}."
                if inputs["insiders"] < 65:
                    support += " The insider component does not add strong confirmation in this model snapshot."
                support += " Company disclosures remain the test of the business case."
                add("model_support", "company", support, ["Top Opportunities"])
        if len(companies) > 1 and top.get("basis") and companies[1].get("basis"):
            other = companies[1]
            margin = top["opportunity"] - other["opportunity"]
            uncapped = all(abs(sum(row["basis"].values())) <= 8 and 0 < row["structural"] + sum(row["basis"].values()) < 100
                           for row in (top, other))
            if abs(margin) < 0.05:
                comparison = f"{top['name']} and {other['name']} are tied on the displayed opportunity score. Their ordering alone does not establish a meaningful advantage."
            elif margin > 0 and uncapped:
                differences = {key: top["basis"][key] - other["basis"][key] for key in top["basis"]}
                differences["structural"] = top["structural"] - other["structural"]
                driver = max(differences, key=differences.get)
                explanations = {
                    "price": "Its stronger price reading is the largest advantage in the scoring model.",
                    "news": "Headline activity supplies the largest scoring advantage. This measures attention; it does not verify a company announcement.",
                    "volume": "Its volume input supplies the largest scoring advantage; the latest volume still needs a fresh check.",
                    "risk": "Its score-risk adjustment is more favorable in the model; setup risk still requires the trade-plan checks.",
                    "revision": "Changes in structural model scores are more favorable for it in this comparison.",
                    "structural": f"Its longer-term structural support is stronger, at {top['structural']:g} versus {other['structural']:g}."}
                comparison = f"Why it leads: {top['name']}'s displayed advantage over {other['name']} is {margin:.1f} points. " + explanations[driver]
                if driver != "structural" and other["structural"] - top["structural"] >= 0.5:
                    comparison += f" {other['name']} retains stronger structural support, {other['structural']:g} versus {top['structural']:g}."
                if margin < 1:
                    comparison += " This is a narrow model lead; a small change in the inputs could reverse it."
            else:
                comparison = "Score caps affect this comparison, so the point adjustments alone do not establish which input explains the final ordering."
            add("ranking_reason", "company", comparison, ["Top Opportunities"])
        if top["price"] is not None:
            change = top["price"]
            price = f"{top['name']} {'rose' if change > 0 else 'fell'} {abs(change):.1f} percent in the quoted regular session." if change else f"{top['name']} was unchanged in the quoted regular session."
            if change < 0:
                price += " Its high ranking therefore still needs stronger price confirmation."
            elif change > 0:
                price += " That adds price support to the research case; volume still needs a separate check."
            add("company_price", "company", price, ["Top Opportunities", "Market Snapshot"])
        risk_words = {"Low": "low", "Medium": "medium", "High": "high", "Medium-High": "medium to high", "Low-Medium": "low to medium"}
        if top["setup_risk"]:
            risk = f"Our analysis rates {top['name']}'s setup risk {risk_words[top['setup_risk']]}"
            if top["score_risk"]:
                risk += f", with {top['score_risk'].lower()} score risk"
            risk += "."
            add("setup_risk", "watch", risk, ["Top Opportunities", "Trade Plan Snapshot"])
        if top["action"] == "wait":
            condition = f"Our trade plan for {top['name']} calls for waiting for price, volume and news confirmation. A high rank alone does not satisfy those checks."
        elif top["action"] == "constructive":
            condition = f"Our trade plan for {top['name']} favors confirmed strength. Watch for price and volume to improve together, then recheck the company's news and setup risk."
        else:
            condition = "The research ranking supplies a review order. Current price, volume and company disclosures still need to support the case before conviction increases."
        add("confirmation", "watch", condition, ["Top Opportunities"] + (["Trade Plan Snapshot"] if top["action"] else []))
    if presentation == "news":
        insights = [row for row in insights if row["id"] not in {"model_support", "ranking_reason"}]
        for row in insights:
            if row["id"] == "company_price":
                row["section"] = "watch"
        if evidence.get("reader_version") == 1:
            from src.intelligence.reader_brief import insights as reader_insights
            insights = [row for row in insights if row["section"] != "watch"] + reader_insights(evidence)
    return insights


def review_company_catalyst(evidence: dict) -> dict:
    """Explain the next research checks without changing numerical scores."""
    calendar = evidence.get("calendar", {})
    events = evidence.get("events", [])
    if calendar.get("status") == "conflict":
        focus = "Resolve earnings date"
        interpretation = "The cached calendar lists conflicting earnings dates. Check the company's investor-relations announcement."
    elif calendar.get("status") == "confirmed":
        focus = "Review company-confirmed schedule"
        interpretation = "The original company announcement establishes this schedule. Review the results, guidance and current price response when released."
    elif calendar.get("dates"):
        focus = "Confirm earnings schedule"
        interpretation = "The earnings date is a Nasdaq estimate. Confirm the company announcement, release timing and guidance before changing conviction."
    elif any(not event.get("official") for event in events):
        focus = "Confirm company development"
        interpretation = "A headline report is not company confirmation. Check the original announcement, commercial timing and execution costs."
    elif events:
        focus = "Review announced development"
        interpretation = "A sourced announcement deserves follow-up on demand, timing, costs and guidance; it does not establish revenue or a buy signal."
    else:
        focus = "Complete catalyst checks"
        interpretation = "No dated company catalyst is established in the available cached window. Check investor relations and current news."
    return {"focus": focus, "interpretation": interpretation,
            "confirmation": "Price and volume confirmation still need a fresh check.", "score_changes": False}


def reported_development_focus(topic: str) -> str:
    """Investor follow-up appropriate to the type of original-source report."""
    return {
        "earnings": "Investor focus: compare revenue, margins and cash flow with prior guidance, then check management's outlook.",
        "guidance": "Investor focus: check what changed in the outlook and which demand, pricing or cost assumptions support it.",
        "contract": "Investor focus: check funded commitments and revenue timing; the announced contract value may be recognized over several periods.",
        "acquisition": "Investor focus: examine the funding, approvals and integration risks before assuming the deal will close.",
        "risk": "Investor focus: establish the affected business and potential financial exposure before changing the investment case.",
        "regulation": "Investor focus: establish the affected products, markets and compliance costs before estimating the earnings impact.",
        "operations": "Investor focus: check the effect on capacity, costs and the company's revenue outlook.",
        "capital": "Investor focus: compare the capital commitment with cash generation, debt and other funding needs.",
        "investment": "Investor focus: compare the spending timetable with expected capacity and future cash generation.",
        "leadership": "Investor focus: watch whether the leadership change alters strategy, capital allocation or guidance.",
    }.get(topic, "Commercial timing and impact still require review.")


def review_sourced_development(story: dict) -> dict:
    """Tie each investor interpretation to the admitted event and release facts."""
    from src.intelligence.story_analysis import investor_read
    return investor_read(story)


def safe_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any, max_length: int = 180) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def get_value(data: dict, keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value

    return default


def get_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


def get_final_score(stock: dict) -> float:
    return get_score(
        stock,
        "final_score",
        "score",
        "smart_money_score",
        "total_score",
        "rating_score",
    )


def get_congress_score_value(stock: dict) -> float:
    return get_score(stock, "congress_score", default=50)


def get_insider_score_value(stock: dict) -> float:
    return get_score(stock, "insider_score", default=50)


def get_stability_score(stock: dict) -> float:
    return get_score(stock, "defense_score", "stability_score", default=50)


def get_category(stock: dict) -> str:
    return clean_text(
        get_value(stock, ["category", "sector", "industry"], "Uncategorized"),
        120,
    )


def get_strength(stock: dict) -> str:
    strengths = get_value(stock, ["strengths", "pros", "bull_case"], [])

    if isinstance(strengths, list):
        for item in strengths:
            text = clean_text(item, 140)
            if text:
                return text

    if isinstance(strengths, str) and strengths.strip():
        return clean_text(strengths, 140)

    reason = get_value(stock, ["reason", "thesis", "summary"], "")

    if reason:
        return clean_text(reason, 140)

    return "No clear strength detail available yet."


def get_weakness(stock: dict) -> str:
    weaknesses = get_value(stock, ["weaknesses", "cons", "bear_case", "risks"], [])

    if isinstance(weaknesses, list):
        for item in weaknesses:
            text = clean_text(item, 140)
            if text:
                return text

    if isinstance(weaknesses, str) and weaknesses.strip():
        return clean_text(weaknesses, 140)

    return "Risk should be reviewed before upgrading conviction."


def get_signal_overlap(stock: dict) -> int:
    overlap = 0

    if get_final_score(stock) >= 75:
        overlap += 1

    if get_congress_score_value(stock) >= 65:
        overlap += 1

    if get_insider_score_value(stock) >= 65:
        overlap += 1

    if get_stability_score(stock) >= 75:
        overlap += 1

    return overlap


def get_signal_phrase(stock: dict) -> str:
    signals = []

    if get_final_score(stock) >= 75:
        signals.append("core quality")

    if get_congress_score_value(stock) >= 65:
        signals.append("Congress activity")

    if get_insider_score_value(stock) >= 65:
        signals.append("insider activity")

    if get_stability_score(stock) >= 75:
        signals.append("stability")

    if not signals:
        return "limited confirmation"

    if len(signals) == 1:
        return signals[0]

    return ", ".join(signals[:-1]) + f", and {signals[-1]}"


def get_risk_tone(stock: dict) -> str:
    text = f"{get_display_risk_label(stock)} {get_category(stock)}".upper()

    if any(
        word in text
        for word in ["HIGH", "SPECULATIVE", "VOLATILE", "EARLY STAGE", "AGGRESSIVE"]
    ):
        return "higher-risk"

    if any(
        word in text
        for word in ["LOW", "DEFENSIVE", "CONTROLLED", "CORE", "STABLE", "QUALITY"]
    ):
        return "controlled-risk"

    return "balanced-risk"


def rank_stocks(stocks: list[dict]) -> list[dict]:
    return sorted(
        stocks or [],
        key=lambda stock: (
            get_signal_overlap(stock),
            get_final_score(stock),
            get_congress_score_value(stock) + get_insider_score_value(stock),
            get_stability_score(stock),
        ),
        reverse=True,
    )


def normalize_stocks(scores: Any) -> list[dict]:
    if not scores:
        return []

    if isinstance(scores, list):
        return [
            stock
            for stock in scores
            if isinstance(stock, dict)
        ]

    if isinstance(scores, dict):
        normalized = []

        for symbol, value in scores.items():
            if isinstance(value, dict):
                stock = dict(value)
                stock.setdefault("ticker", symbol)
                normalized.append(stock)
            else:
                normalized.append(
                    {
                        "ticker": symbol,
                        "final_score": value,
                    }
                )

        return normalized

    return []


def get_setup_type(stock: dict) -> str:
    category = get_category(stock).upper()
    risk_tone = get_risk_tone(stock)
    label = get_smart_money_label(stock)
    congress = get_congress_score_value(stock)
    insider = get_insider_score_value(stock)

    if "DIVIDEND" in category or "INCOME" in category:
        return "income and stability setup"

    if "CYBER" in category:
        return "cybersecurity growth setup"

    if "DEFENSE" in category or "DRONE" in category or "WARFARE" in category:
        return "defense and national-security setup"

    if "AI" in category or "GROWTH" in category:
        if risk_tone == "higher-risk":
            return "aggressive AI growth setup"
        return "AI growth setup"

    if "HIGH CONVICTION" in label.upper() or "PRIME" in label.upper():
        return "quality compounder setup"

    if congress >= 65 and insider >= 65:
        return "smart-money confirmation setup"

    if "STRONG WATCH" in label.upper():
        return "strong watchlist setup"

    return "early watchlist setup"


def get_conviction_level(stock: dict) -> str:
    label = get_smart_money_label(stock)
    signal = get_signal_strength(stock)
    risk_tone = get_risk_tone(stock)

    if label in {"Prime Opportunity", "High Conviction"} and signal in {"Confirmed", "Strong"} and risk_tone != "higher-risk":
        return "High conviction"

    if label in {"High Conviction", "Strong Watch"} and signal in {"Strong", "Improving"}:
        return "Positive watch"

    if signal in {"Improving", "Early"}:
        return "Developing conviction"

    if label in {"Developing Watch", "Early Watch"}:
        return "Watchlist candidate"

    return "Low conviction"


def get_position_style(stock: dict) -> str:
    risk_tone = get_risk_tone(stock)
    signal = get_signal_strength(stock)
    label = get_smart_money_label(stock)
    category = get_category(stock).upper()

    if risk_tone == "higher-risk":
        return "best treated as a smaller, speculative position until confirmation improves"

    if "DIVIDEND" in category or "INCOME" in category:
        return "better suited for an income or defensive sleeve than an aggressive growth sleeve"

    if label in {"Prime Opportunity", "High Conviction"} and signal in {"Confirmed", "Strong"}:
        return "suitable for deeper review as a core or high-conviction watchlist candidate"

    if signal in {"Thin", "Early"}:
        return "best kept on watch until more signals confirm the thesis"

    return "appropriate for watchlist review with position size tied to risk tolerance"


def build_core_thesis(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    setup_type = get_setup_type(stock)
    label = get_smart_money_label(stock)
    signal_strength = get_signal_strength(stock)
    portfolio_fit = get_portfolio_fit(stock)
    action_label = get_action_label(stock)
    signal_phrase = get_signal_phrase(stock)
    risk_tone = get_risk_tone(stock)
    strength = get_strength(stock)

    return (
        f"{symbol} currently screens as a {setup_type}. "
        f"The Smart Money view is {label}, with {signal_strength.lower()} confirmation "
        f"and a {portfolio_fit.lower()} profile. "
        f"The setup is led by {signal_phrase}. "
        f"The thesis is strongest when viewed as a {risk_tone} idea where the key positive is: {strength} "
        f"The current action label is: {action_label}."
    )


def build_confirmation_logic(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    congress = get_congress_score_value(stock)
    insider = get_insider_score_value(stock)
    stability = get_stability_score(stock)
    label = get_smart_money_label(stock)

    confirmations = []

    if label in {"Prime Opportunity", "High Conviction", "Strong Watch"}:
        confirmations.append("the Smart Money rating is strong enough to justify continued review")

    if congress >= 65:
        confirmations.append("Congress activity is supportive")

    if insider >= 65:
        confirmations.append("insider activity adds confirmation")

    if stability >= 75:
        confirmations.append("the stability profile helps reduce setup risk")

    if not confirmations:
        return (
            f"{symbol} does not yet have strong confirmation. "
            "The setup needs better quality, smart-money activity, or risk support before conviction improves."
        )

    if len(confirmations) == 1:
        return f"Confirmation is still narrow: {confirmations[0]}."

    return "Confirmation is improving because " + ", ".join(confirmations[:-1]) + f", and {confirmations[-1]}."


def build_break_thesis_logic(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    risk_tone = get_risk_tone(stock)
    weakness = get_weakness(stock)
    signal_strength = get_signal_strength(stock)
    label = get_smart_money_label(stock)

    if risk_tone == "higher-risk":
        return (
            "The thesis weakens if volatility expands, the stock loses momentum, "
            "or the risk profile stops matching the expected upside. "
            f"Main risk to review: {weakness}"
        )

    if signal_strength in {"Thin", "Early"}:
        return (
            f"The thesis weakens if {symbol} cannot add more confirmation from smart-money activity, "
            f"price action, or stability. Main risk to review: {weakness}"
        )

    if label in {"Neutral", "Weak Signal"}:
        return (
            "The thesis weakens if the rating remains below watchlist quality. "
            f"Main risk to review: {weakness}"
        )

    return (
        "The thesis weakens if current signal confirmation fades or if the risk profile deteriorates. "
        f"Main risk to review: {weakness}"
    )


def build_next_step_logic(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    risk_tone = get_risk_tone(stock)
    signal_strength = get_signal_strength(stock)

    if risk_tone == "higher-risk":
        return f"Next step: run /risk {symbol} and /scorecard {symbol} before treating this as anything more than a speculative watch."

    if signal_strength in {"Confirmed", "Strong"}:
        return f"Next step: run /scorecard {symbol}, then compare it against /portfolio {symbol} to decide its best role."

    if signal_strength == "Improving":
        return f"Next step: run /smartmoney {symbol} and /conviction {symbol} to confirm whether the signal stack is improving."

    return f"Next step: keep {symbol} on watch and rerun /analyst {symbol} after fresh Congress, insider, or market data updates."


def build_single_stock_analysis(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    category = get_category(stock)
    conviction = get_conviction_level(stock)
    setup_type = get_setup_type(stock)
    position_style = get_position_style(stock)

    return f"""
{symbol} Analyst Read

Smart Money View:
{format_stock_label_block(stock)}

Conviction: {conviction}
Setup Type: {setup_type}
Category: {category}

Thesis:
{build_core_thesis(stock)}

Why It Matters:
{build_confirmation_logic(stock)}

Portfolio Role:
{symbol} is {position_style}.

What Could Break The Thesis:
{build_break_thesis_logic(stock)}

Analyst Take:
Favor {symbol} only if the thesis, risk profile, and signal confirmation still line up. A strong label alone is not enough; the best ideas need confirmation, role fit, and risk control.

{build_next_step_logic(stock)}
""".strip()


def build_ranked_analyst_summary(stocks: list[dict], limit: int = DEFAULT_MAX_ITEMS) -> str:
    ranked = rank_stocks(stocks)[:limit]

    if not ranked:
        return "No ranked analyst opportunities are available."

    lines = []

    for index, stock in enumerate(ranked, start=1):
        symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        category = get_category(stock)

        lines.append(
            f"{index}. {symbol} — {get_smart_money_label(stock)}\n"
            f"   Signal: {get_signal_strength(stock)}\n"
            f"   Fit: {get_portfolio_fit(stock)}\n"
            f"   Action: {get_action_label(stock)}\n"
            f"   Setup: {get_setup_type(stock)}\n"
            f"   Category: {category}"
        )

    return "\n\n".join(lines)


def build_market_analyst_take(stocks: list[dict]) -> str:
    if not stocks:
        return "Market analyst take unavailable because no scoring data was provided."

    ranked = rank_stocks(stocks)
    top = ranked[0]

    top_symbol = clean_symbol(get_value(top, ["ticker", "symbol", "name"], "UNKNOWN"))
    top_label = get_smart_money_label(top)
    top_signal = get_signal_strength(top)
    top_fit = get_portfolio_fit(top)

    strong_names = [
        clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        for stock in ranked
        if get_smart_money_label(stock) in {"Prime Opportunity", "High Conviction", "Strong Watch"}
    ]

    confirmed_names = [
        clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        for stock in ranked
        if get_signal_strength(stock) in {"Confirmed", "Strong"}
    ]

    higher_risk_names = [
        clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        for stock in ranked
        if get_risk_tone(stock) == "higher-risk"
    ]

    strong_text = ", ".join(strong_names[:4]) if strong_names else "none yet"
    confirmed_text = ", ".join(confirmed_names[:4]) if confirmed_names else "none yet"
    risk_text = ", ".join(higher_risk_names[:4]) if higher_risk_names else "limited"

    return (
        f"{top_symbol} leads the analyst board as a {top_label} idea with {top_signal.lower()} confirmation "
        f"and a {top_fit.lower()} profile. "
        f"The strongest watchlist names right now are: {strong_text}. "
        f"The cleanest confirmation appears in: {confirmed_text}. "
        f"Higher-risk names to size carefully: {risk_text}. "
        "The best setups are the names where Smart Money rating, signal confirmation, portfolio fit, and risk control agree."
    )


def build_analyst_summary(scores: Any, symbol: str | None = None, limit: int = DEFAULT_MAX_ITEMS) -> str:
    stocks = normalize_stocks(scores)

    if symbol:
        wanted = clean_symbol(symbol)

        for stock in stocks:
            current_symbol = clean_symbol(
                get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN")
            )

            if current_symbol == wanted:
                return build_single_stock_analysis(stock)

        return f"No analyst data found for {wanted}."

    if not stocks:
        return "No analyst data available."

    return f"""
Smart Money AI Analyst Summary

Market Read:
{build_market_analyst_take(stocks)}

Top Analyst Ideas:
{build_ranked_analyst_summary(stocks, limit=limit)}

Bottom Line:
Focus on names with strong Smart Money ratings, improving or confirmed signals, and a risk profile that matches the intended portfolio role.
""".strip()


def generate_ai_summary(scores: Any) -> str:
    """
    Backward-compatible wrapper for older report code.
    """
    return build_analyst_summary(scores=scores, symbol=None, limit=4)


def generate_analyst_summary(scores: Any, symbol: str | None = None) -> str:
    """
    Compatibility wrapper for agent-style callers.
    """
    return build_analyst_summary(scores=scores, symbol=symbol, limit=5)


def analyze_stock(stock: Any) -> str:
    """
    Compatibility helper for single-stock callers.

    Accepts either:
    - a stock dictionary
    - a ticker string
    """

    if isinstance(stock, dict):
        return build_single_stock_analysis(stock)

    symbol = clean_symbol(stock)

    return f"""
{symbol} Analyst Read

Analyst data for {symbol} was requested, but only a ticker symbol was provided.
Use analyze_ticker(scores, "{symbol}") when full scoring data is available.

Analyst Take:
A ticker alone is not enough for a full Smart Money AI read. The agent needs rating, category, signal, and risk data to produce a complete analysis.
""".strip()


def analyze_ticker(scores: Any, ticker: str) -> str:
    """
    Compatibility helper for ticker-based callers.

    First checks the curated Smart Money scoring list.
    If the ticker is not found, it builds a fallback analyst read so
    /analyst can work with tickers outside the internal watchlist.
    """
    symbol = clean_symbol(ticker)

    result = build_analyst_summary(scores=scores, symbol=symbol, limit=5)

    if not result.startswith("No analyst data found"):
        return result

    try:
        from src.scoring.scoring_engine import score_ticker

        fallback_stock = score_ticker(symbol)
        fallback_report = build_single_stock_analysis(fallback_stock)

        return f"""
{fallback_report}

Coverage Note:
{symbol} is not currently part of the curated Smart Money watchlist, so this is a fallback analyst read. For stronger analysis, add {symbol} to the scoring watchlist with a category, smart score, and stability profile.
""".strip()

    except Exception as error:
        return f"""
{symbol} Analyst Read

No curated Smart Money analyst data was found for {symbol}, and the fallback analyst read could not be built.

Error:
{type(error).__name__}

Next Step:
Add {symbol} to the Smart Money scoring watchlist or run /ticker {symbol} for a market-data style read.
""".strip()


def review_special_event(event: dict, scores: Any) -> dict:
    """Review supplied evidence using the existing analyst rules, without changing scores."""
    from src.reports.tradeplan_language import plain_tradeplan_read
    from src.utils.report_consistency import score_risk_label

    stocks = normalize_stocks(scores)
    wanted = set(event.get("symbols", []))
    if event.get("kind") == "market":
        selected = [stock for stock in rank_stocks(stocks)
                    if any(term in get_category(stock).lower() for term in ("ai", "growth", "semiconductor", "cyber"))][:4]
        interpretation = "Review growth/AI concentration and confirmation before adding risk. Price data alone does not establish the cause."
        checks = "Confirm price/volume, near-term earnings and macro releases; review position size and thesis invalidation."
    elif event.get("kind") == "ipo":
        from src.intelligence.ipo_monitor import checked, interpretation as ipo_interpretation
        checked(event["evidence"])
        selected = []
        interpretation = ipo_interpretation(event["evidence"])
        checks = "Verify the original filing, offering terms, revenue quality, losses, cash requirements, dilution and governance. Review AI concentration separately from any decision to buy the IPO."
    else:
        selected = [stock for stock in stocks if clean_symbol(stock.get("ticker") or stock.get("symbol")) in wanted][:3]
        official = event.get("evidence", {}).get("official", False)
        interpretation = ("Company announcement available. " if official else "Headline-only report; company confirmation pending. ")
        reads = {
            "product": ("Validate the product stage, timing, demand and execution costs before changing conviction.",
                        "Confirm the original announcement, commercial availability, pricing, margins and guidance."),
            "contract": ("Validate contract economics and funded commitments; a partnership announcement does not establish booked revenue.",
                         "Confirm counterparties, contract value, duration, funding, milestones and revenue recognition."),
            "earnings": ("Assess actual results against prior guidance and expectations; headline growth alone does not establish an attractive setup.",
                         "Check revenue, margins, cash flow, segment results, guidance and the earnings transcript."),
            "guidance": ("Verify the direction and scope of the guidance change and the assumptions behind it.",
                         "Compare new and prior guidance, management assumptions, margins and cash-flow implications."),
            "risk": ("Validate the reported risk and affected operations; financial impact is not established by the headline.",
                     "Check the original disclosure, severity, operational exposure, remediation and thesis invalidation."),
            "acquisition": ("Assess announced deal terms, financing and execution risk; completion remains subject to closing conditions.",
                            "Verify consideration, funding, approvals, expected closing and integration assumptions."),
        }
        detail, checks = reads.get(event.get("event_type", "product"), reads["product"])
        interpretation += detail
    context = []
    for stock in selected:
        ticker = clean_symbol(stock.get("ticker") or stock.get("symbol"))
        has_score = any(stock.get(key) is not None for key in ("final_score", "score", "smart_money_score", "total_score"))
        setup = plain_tradeplan_read(stock).get("risk", "Unavailable") if has_score else "Unavailable"
        score_risk = score_risk_label(stock) if has_score else "Unavailable"
        # Use the same risk measures as /report, /tradeplan and /scorecard.
        context.append(f"{ticker} — Score Risk: {score_risk}; Setup Risk: {setup}")
    if not context:
        context = ["No IPO score inferred; related public stocks are separate research."] if event.get("kind") == "ipo" else ["Existing score coverage unavailable for the affected company."]
    return {"interpretation": interpretation, "checks": checks,
            "model_context": context, "symbols": [clean_symbol(stock.get("ticker") or stock.get("symbol")) for stock in selected] or sorted(wanted),
            "mode": "existing analyst rules", "score_changes": False}


def format_special_event_review(review: dict) -> str:
    return ("Agent review\nInterpretation: " + review["interpretation"]
            + "\nExisting model context: " + " | ".join(review["model_context"])
            + "\nValidation: " + review["checks"])


def run_analyst_agent(scores: Any, symbol: str | None = None, event_context: dict | None = None) -> str:
    """
    Main deterministic analyst-agent entry point.
    """
    if event_context is not None:
        return format_special_event_review(review_special_event(event_context, scores))
    return build_analyst_summary(scores=scores, symbol=symbol, limit=5)
