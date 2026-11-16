"""Compare the same quoted names across two completed regular sessions."""

from datetime import date
import re

from src.intelligence.special_alert_sources import NY, timestamp


SOURCE_SECTION = "Prior watchlist closes"
CLOSES = "Watchlist closes vs "
DAY = r"(\d{4}-\d{2}-\d{2})"
BREADTH = r"^Breadth: (\d{1,3}) up / (\d{1,3}) down / (\d{1,3}) quoted$"
SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


def market_snapshot(report):
    from src.reports.report_quality import split_report_sections

    return next(("\n".join(lines[1:]).rstrip() for header, lines in split_report_sections(report)
                 if header == "Market Snapshot"), "")


def closing_snapshot(snapshot):
    sessions = re.findall(r"^Quote session: " + DAY + r"$", snapshot, re.M)
    rows = re.findall(r"^" + CLOSES + DAY + r" — (.+)$", snapshot, re.M)
    counts = re.findall(BREADTH, snapshot, re.M)
    if (not re.match(r"Market Session: Closed\b", snapshot) or len(sessions) != 1
            or len(rows) != 1 or len(counts) != 1):
        return None
    previous, values = rows[0]
    try:
        session_day, previous_day = date.fromisoformat(sessions[0]), date.fromisoformat(previous)
    except ValueError:
        return None
    if not 1 <= (session_day - previous_day).days <= 4 or max(session_day.weekday(), previous_day.weekday()) >= 5:
        return None
    directions = {}
    for entry in values.split(", "):
        symbol, _, direction = entry.partition(" ")
        if not SYMBOL.fullmatch(symbol) or direction not in {"up", "down", "flat"} or symbol in directions:
            return None
        directions[symbol] = direction
    up, down, total = map(int, counts[0])
    if (total != len(directions) or up != sum(value == "up" for value in directions.values())
            or down != sum(value == "down" for value in directions.values())):
        return None
    return {"session": sessions[0], "previous_session": previous, "directions": directions}


def attach_completed_closes(report, movers, max_chars):
    """Keep the same quote cohort that supplied the written breadth count."""
    if not movers:
        return report
    session, previous = movers[0].get("session_date"), movers[0].get("previous_session_date")
    if not session or not previous or any(
        row.get("quote_timing") != "completed_session" or row.get("session_date") != session
        or row.get("previous_session_date") != previous for row in movers
    ):
        return report
    directions = []
    for row in sorted(movers, key=lambda row: row["symbol"]):
        move = row["change_percent"]
        direction = "up" if move > 0 else "down" if move < 0 else "flat"
        directions.append(f"{row['symbol']} {direction}")
    close_line = f"{CLOSES}{previous} — " + ", ".join(directions)
    if len(report) + len(close_line) + 1 > max_chars:
        return report
    snapshot = market_snapshot(report)
    with_closes = snapshot + "\n" + close_line
    packet = closing_snapshot(with_closes)
    if not packet or packet["session"] != session:
        return report
    return report.replace("Market Snapshot\n" + snapshot, "Market Snapshot\n" + with_closes, 1)


def compare(current, baseline, now):
    if not current or not isinstance(baseline, dict):
        return None
    snapshot = baseline.get("snapshot")
    edition_id = baseline.get("edition_id")
    recorded = timestamp(baseline.get("generated_at"))
    if (not isinstance(snapshot, str) or len(snapshot) > 2000
            or not isinstance(edition_id, str) or not re.fullmatch(r"[0-9a-f]{20}", edition_id)
            or recorded is None or recorded >= now):
        return None
    prior = closing_snapshot(snapshot)
    if (not prior or prior["session"] != current["previous_session"]
            or prior["session"] > recorded.astimezone(NY).date().isoformat()
            or current["session"] > now.astimezone(NY).date().isoformat()):
        return None
    old, new = prior["directions"], current["directions"]
    symbols = sorted(old.keys() & new.keys())
    if len(symbols) < 2:
        return None
    return {
        "edition_id": edition_id,
        "previous_session": prior["session"],
        "session": current["session"],
        "symbols": symbols,
        "previous_down": sum(old[symbol] == "down" for symbol in symbols),
        "down": sum(new[symbol] == "down" for symbol in symbols),
        "up": sum(new[symbol] == "up" for symbol in symbols),
    }


def prior_edition(report, editions, now):
    current = closing_snapshot(market_snapshot(report))
    if not current:
        return None
    for edition in editions:
        evidence = (edition.get("analyst_review") or {}).get("evidence", {})
        if evidence.get("session") != current["previous_session"]:
            continue
        # The store verifies the hashes of both texts before returning a voice-ready edition.
        prior_report = edition.get("research_text")
        if (not edition.get("voiceover") or not isinstance(prior_report, str)
                or not any(row["name"] == "Editorial Review" and row["status"] == "pass" for row in edition["stages"])):
            continue
        baseline = {"edition_id": edition["id"], "generated_at": edition["generated_at"],
                    "snapshot": market_snapshot(prior_report)}
        if compare(current, baseline, now):
            return baseline
    return None


def watch_copy(comparison):
    previous, session = (date.fromisoformat(comparison[key]) for key in ("previous_session", "session"))
    total = len(comparison["symbols"])
    down, up = comparison["down"], comparison["up"]
    earlier = f"{previous:%B} {previous.day}"
    later = f"{session:%B} {session.day}"
    result = (f"Of {total} watchlist names quoted at both closes, "
              f"{comparison['previous_down']} finished lower on {earlier} and {down} on {later}.")
    majority = total // 2 + 1
    if down >= majority:
        check = f"Watch whether the next close brings the number of decliners down to {majority - 1} or fewer."
    elif up >= majority:
        check = f"{up} advanced at the latest close. Watch whether at least {majority} do so again."
    else:
        check = f"Watch for at least {majority} advances at the next close to see if gains reach a majority."
    return "Watchlist follow-through — " + result + " " + check
