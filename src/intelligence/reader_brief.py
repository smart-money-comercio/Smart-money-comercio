"""Plain-language opening and follow-up signals from the frozen research edition."""

from src.intelligence.daily_brief_analysis import NAMES
from src.intelligence.company_focus import issuer


def company_name(story):
    symbol = story.get("publisher_symbol") or next(iter(story.get("symbols", [])), "")
    return NAMES.get(symbol, symbol), issuer(symbol)


def opening(evidence):
    moves, breadth = evidence["moves"], evidence["breadth"]
    events = evidence.get("market_event_context", {}).get("events", [])
    checked = next((row for row in events if row["status"] == "rechecked"), None)
    if checked:
        label = NAMES.get(checked["symbol"], checked["symbol"])
        down = checked["reported_move"] < 0
        text = f"The takeaway: {label}'s sharp {'decline' if down else 'advance'} stands out in the quoted session. "
        text += ("The key question is whether company disclosures change the business outlook, and whether selling spreads to other names." if down else
                 "The key question is whether company disclosures support the move, and whether other companies join the advance.")
        return text
    if all(key in moves for key in ("Nasdaq", "Russell")) and moves["Nasdaq"] < 0 < moves["Russell"]:
        return ("The takeaway: The Nasdaq is lower while smaller-company stocks are higher. "
                "This is an uneven session; the next test is whether selling stays concentrated or spreads across more companies.")
    if moves.get("Oil", 0) >= 1.5:
        return ("The takeaway: Rising oil prices put business costs in focus. "
                "If energy stays expensive, companies will need stronger pricing or lower costs elsewhere to protect profits. That's the test behind today's research.")
    indexes = [moves[key] for key in ("S&P", "Nasdaq", "Russell") if key in moves]
    if len(indexes) == 3 and all(value > 0 for value in indexes):
        if breadth and breadth["down"] > breadth["up"]:
            return ("The takeaway: The major indexes are higher, but more of the stocks and funds we follow are lower. "
                    "The rally would look stronger if gains spread to more of the businesses we track.")
        return ("The takeaway: All three major indexes we track are higher in the quoted session. "
                "The next test is whether gains hold and company results support the optimism; one strong session cannot answer both questions.")
    if len(indexes) == 3 and all(value < 0 for value in indexes):
        return ("The takeaway: All three major indexes we track are lower in the quoted session. "
                "We're looking for selling to ease and company results to support a recovery before treating a bounce as a lasting improvement.")
    if len(indexes) >= 2:
        return ("The takeaway: The quoted indexes give a mixed signal. "
                "Company results and the number of stocks joining the next move will help separate a lasting improvement from a short-lived bounce.")
    return ("The takeaway: Market coverage is incomplete, so a broad market call would be premature. "
            "The useful focus is what verified company announcements actually change, and which missing figures we still need before judging the wider picture.")


def watching(evidence):
    """Two or three concrete checks: observed fact, next signal, meaning."""
    rows = []
    breadth, moves = evidence["breadth"], evidence["moves"]
    if breadth:
        up, down, total = (breadth[key] for key in ("up", "down", "total"))
        scope = (f"Of the {total} stocks and funds we track, {up} are higher and {down} lower." if evidence["is_open"] else
                 f"Of the {total} stocks and funds we track, {up} finished higher and {down} lower.")
        if down > up:
            if all(key in moves and moves[key] > 0 for key in ("S&P", "Nasdaq", "Russell")):
                scope += " Index gains are not shared by most names in this research watchlist."
            text = "Market recovery: " + scope + " A recovery would look stronger if more names turn positive; continued selling would weaken that case."
        elif up > down:
            text = "Staying power: " + scope + " Watch whether gains hold and more companies join in; a rally led by fewer names would be less convincing."
        else:
            text = "The next move: " + scope + " Watch whether more companies turn higher or lower together; wider participation would help judge the direction."
        rows.append({"id": "watch_participation", "text": text, "sources": ["Market Snapshot", "Executive Summary"]})
    elif moves:
        rows.append({"id": "watch_market", "text": "Market direction: Watch whether the major indexes start moving together. A move shared by more indexes would be more convincing; limited coverage still leaves the overall picture uncertain.",
                     "sources": ["Market Snapshot", "Executive Summary"]})
    else:
        rows.append({"id": "watch_market", "text": "The missing market check: We still need a dated view of the major indexes and current company prices. Until those figures are available, verified company announcements can inform research but cannot establish a broad market trend.",
                     "sources": ["Market Snapshot"]})
    events = evidence.get("market_event_context", {}).get("events", [])
    event = events[0] if events else None
    if event:
        label = NAMES.get(event["symbol"], event["symbol"])
        reported = any(issuer(story.get("publisher_symbol", "")) == event["symbol"]
                       and story.get("event_evidence", {}).get("event") == "earnings" for story in evidence.get("stories", []))
        text = (f"{label}'s business outlook: Watch original results and guidance for changes in sales, costs and spending. "
                "Those details will help judge whether the business outlook changed; the price move alone cannot explain it." if event["status"] == "rechecked" else
                f"{label}'s price check: The unusually large reported move still needs quote and corporate-action confirmation. "
                "A corrected price or a stock split could change the reading; verify that before interpreting the business impact.")
        if reported and event["status"] == "rechecked":
            text = (f"{label}'s next test: Compare management's outlook with the newly reported sales, profits and cash needs. "
                    "That will help judge whether spending is strengthening the business; the price move alone cannot explain it.")
        rows.append({"id": "watch_event", "text": text, "sources": ["Market event checks"]})
    if any(story.get("ipo") for story in evidence.get("stories", [])):
        rows.append({"id": "watch_ipo", "text": "IPO details: Watch the proposed price, share count and new shares being issued. Compare that valuation with the disclosed sales, losses and funding needs before judging the offering's business case.",
                     "sources": ["Verified story decisions"]})
    stories = [row for row in evidence.get("stories", []) if row.get("kind") == "company" and row.get("event_evidence")]
    priority = {"earnings": 0, "guidance": 0, "acquisition": 1, "contract": 1, "product": 2}
    stories.sort(key=lambda row: (priority.get(row["event_evidence"]["event"], 3), row["id"]))
    for story in stories:
        if len(rows) >= 3:
            break
        label, symbol = company_name(story)
        if event and symbol == event["symbol"]:
            continue
        profile = story["event_evidence"]
        kind, stage = profile["event"], profile["stage"]
        if kind in {"earnings", "guidance"}:
            text = f"{label}'s next results: Compare sales, profits and cash generation with management's outlook. Stronger sales that also produce cash would support the business case; weaker guidance would call it into question."
        elif kind in {"contract", "acquisition"} and stage == "terminated":
            text = f"{label}'s lost deal: Watch cancellation costs and revised company guidance. Those disclosures will help show whether replacement business can offset the lost opportunity."
        elif kind == "contract" and stage == "cooperation":
            text = f"{label}'s proposed partnership: Watch for signed commercial terms, customer commitments and a delivery timetable. An agreement to explore an opportunity still leaves the eventual sales and costs uncertain."
        elif kind == "contract":
            text = f"{label}'s contract follow-through: Look for committed funding and a start date for the work. Those details will show how much of the potential award can become sales, and when."
        elif kind == "acquisition":
            text = (f"{label}'s acquisition: Watch integration costs and the acquired business's cash contribution. Rising sales would be less useful if the costs of combining the businesses absorb the benefit." if stage == "completed" else
                    f"{label}'s proposed deal: Watch financing and required approvals. The business impact depends on whether the deal closes and what it costs to complete.")
        elif kind == "product" and stage == "test milestone":
            text = f"{label}'s path to sales: Watch for repeat successful tests, funded purchases and delivery dates. A technical success becomes more useful to investors when customers commit money and production costs are clear."
        elif kind in {"product", "capacity expansion", "technology collaboration"}:
            text = f"{label}'s commercial test: Look for paying customers and the cost of serving them. Growing usage would support the investment case more clearly if it also improves sales, profits and cash generation."
        elif kind == "restructuring":
            text = f"{label}'s cost changes: Watch disclosed savings, one-time charges and service capacity. Lower spending would help only if the business can keep serving customers and protect future sales."
        else:
            continue
        rows.append({"id": "watch_business", "text": text, "sources": ["Verified story decisions"]})
        break
    if len(rows) < 3 and moves.get("Oil", 0) >= 1.5:
        rows.append({"id": "watch_energy", "text": "Energy costs: Watch whether oil's rise lasts and whether companies warn about higher fuel or shipping bills. Passing those costs to customers could protect profits; absorbing them could reduce margins.",
                     "sources": ["Executive Summary", "Market Snapshot"]})
    if len(rows) == 1:
        rows.append({"id": "watch_results", "text": "The earnings reality check: In the next company updates, look for sales growth that also produces profits and cash. More spending or higher usage alone would leave the return on that investment uncertain.",
                     "sources": ["Company focus selection"] if evidence.get("company_focus") else ["Top Opportunities"]})
    return [{**row, "section": "watch"} for row in rows[:evidence.get("reader_limit", 3)]]


def insights(evidence):
    sources = ["Executive Summary", "Market Snapshot"]
    if evidence.get("market_event_context", {}).get("events"):
        sources.append("Market event checks")
    return [{"id": "opening_takeaway", "section": "intro", "text": opening(evidence), "sources": sources}, *watching(evidence)]
