"""Compare the same quoted names across two completed regular sessions."""

from datetime import date
import re

from src.intelligence.special_alert_sources import NY, timestamp


SOURCE_SECTION = "Prior watchlist closes"
CHECKPOINT_SOURCE = "Delivered watchlist checkpoint"
CHECKPOINT_VERSION = 2
WATCH_LABEL = "Watchlist follow-through — "
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


def compare(current, baseline, now, *, version=1):
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
    comparison = {
        "edition_id": edition_id,
        "previous_session": prior["session"],
        "session": current["session"],
        "symbols": symbols,
        "previous_down": sum(old[symbol] == "down" for symbol in symbols),
        "down": sum(new[symbol] == "down" for symbol in symbols),
        "up": sum(new[symbol] == "up" for symbol in symbols),
    }
    if version == 2:
        comparison.update(prior_total=len(old),
                          fell_again=sum(old[symbol] == new[symbol] == "down" for symbol in symbols))
    return comparison


def prior_edition(report, editions, now, *, version=1, confirmed_ids=()):
    current = closing_snapshot(market_snapshot(report))
    if not current:
        return None
    fallback = None
    best_rank = None
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
        if not compare(current, baseline, now):
            continue
        if version != 2:
            return baseline
        # A premarket rebuild can rotate symbols while still quoting yesterday's close.
        # Prefer the cohort already on record before the new session's local date.
        before_session = timestamp(baseline["generated_at"]).astimezone(NY).date().isoformat() < current["session"]
        rank = (before_session, edition["id"] in confirmed_ids)
        if rank == (True, True):
            return baseline
        if best_rank is None or rank > best_rank:
            fallback, best_rank = baseline, rank
    return fallback


def cohort_copy(comparison, previous, session):
    total = len(comparison["symbols"])
    prior_total = comparison["prior_total"]
    before, after = comparison["previous_down"], comparison["down"]
    previous_day, day = previous.strftime("%A"), session.strftime("%A")
    if total < prior_total:
        scope = f"Closing quotes covered {total} of {previous_day}'s {prior_total} watchlist names. In that group, "
    else:
        scope = f"Across the same {total} watchlist names, "
    if before == after:
        change = f"the number of decliners stayed at {after} from {previous_day} to {day}."
    else:
        direction = "narrowed" if after < before else "spread"
        noun = "decliner" if before == 1 else "decliners"
        change = f"selling {direction} from {before} {noun} on {previous_day} to {after} on {day}."
    if before:
        repeat = comparison["fell_again"]
        if before == 1:
            change += f" The one {previous_day} decliner " + ("fell again." if repeat else "did not fall again.")
        elif repeat == 0:
            change += f" None of the names that fell on {previous_day} fell again."
        else:
            change += f" Of the names that fell on {previous_day}, {repeat} fell again."
    return scope + change


def watch_copy(comparison):
    previous, session = (date.fromisoformat(comparison[key]) for key in ("previous_session", "session"))
    total = len(comparison["symbols"])
    down, up = comparison["down"], comparison["up"]
    earlier = f"{previous:%B} {previous.day}"
    later = f"{session:%B} {session.day}"
    result = (f"Of {total} watchlist names quoted at both closes, "
              f"{comparison['previous_down']} finished lower on {earlier} and {down} on {later}.")
    if "fell_again" in comparison:
        result = cohort_copy(comparison, previous, session)
    majority = total // 2 + 1
    if down >= majority:
        check = f"Watch whether the next close brings the number of decliners down to {majority - 1} or fewer."
    elif up >= majority:
        check = f"{up} advanced at the latest close. Watch whether at least {majority} do so again."
    else:
        check = f"Watch for at least {majority} advances at the next close to see if gains reach a majority."
    return WATCH_LABEL + result + " " + check


def delivered_checkpoint(report, editions, confirmed_ids, now):
    """Use the first confirmed brief that printed the checkpoint for the preceding close."""
    by_id = {edition["id"]: edition for edition in editions}
    for edition_id in confirmed_ids:
        edition = by_id.get(edition_id)
        if not edition or not edition.get("voiceover"):
            continue
        analysis = edition["analyst_review"]
        comparison = analysis["evidence"].get("watchlist_follow_through")
        if not comparison or not any(row["name"] == "Editorial Review" and row["status"] == "pass" for row in edition["stages"]):
            continue
        text = watch_copy(comparison)
        if text not in edition["report_text"].splitlines() or not any(
                row["section"] == "watch" and row["text"] == text for row in analysis["insights"]):
            continue
        proof = {"edition_id": edition_id, "generated_at": edition["generated_at"], "text": text,
                 "snapshot": market_snapshot(edition["research_text"]), "baseline": analysis.get("watchlist_baseline")}
        if analysis["evidence"].get("watchlist_checkpoint_version") == 2:
            proof["comparison_version"] = 2
        if evaluate(report, proof, now):
            return proof
    return None


def evaluate(report, proof, now):
    """Reconstruct the original criterion and check it against the same names at the next close."""
    edition_id = proof.get("edition_id", "")
    generated = timestamp(proof.get("generated_at"))
    prior = closing_snapshot(proof.get("snapshot", ""))
    if not re.fullmatch(r"[0-9a-f]{20}", edition_id) or not generated or generated >= now or not prior:
        return None
    version = proof.get("comparison_version", 1)
    if type(version) is not int or version not in (1, 2):
        return None
    comparison = compare(prior, proof.get("baseline"), generated, version=version)
    if not comparison or watch_copy(comparison) != proof.get("text"):
        return None

    snapshot = market_snapshot(report)
    session_day = re.findall(r"^Quote session: " + DAY + r"$", snapshot, re.M)
    if not re.match(r"Market Session: Closed\b", snapshot) or len(session_day) != 1:
        return None
    try:
        session = date.fromisoformat(session_day[0])
    except ValueError:
        return None
    before = date.fromisoformat(prior["session"])
    if (not 1 <= (session - before).days <= 4 or session.weekday() >= 5
            or session > now.astimezone(NY).date()):
        return None
    current = closing_snapshot(snapshot)
    # A verified different predecessor means this was not the promised close.
    if current and current["previous_session"] != prior["session"]:
        return None

    symbols = comparison["symbols"]
    directions = current["directions"] if current else {}
    available = sum(symbol in directions for symbol in symbols)
    total = len(symbols)
    majority = total // 2 + 1
    metric = "down" if comparison["down"] >= majority else "up"
    limit = majority - 1 if metric == "down" else majority
    earlier = comparison[metric]
    result = {"edition_id": edition_id, "previous_session": prior["session"], "session": session.isoformat(),
              "symbols": symbols, "available": available, "metric": metric, "threshold": limit, "previous_count": earlier}
    if available != total:
        return {**result, "status": "limited"}
    count = sum(directions[symbol] == metric for symbol in symbols)
    met = count <= limit if metric == "down" else count >= limit
    return {**result, "status": "met" if met else "missed", "count": count}


def verdict_copy(result):
    session = date.fromisoformat(result["session"])
    day = f"{session:%B} {session.day}"
    total = len(result["symbols"])
    if result["status"] == "limited":
        return (f"Comparable quotes covered {result['available']} of the {total} names in our watchlist check at the {day} close. "
                "The outcome needs a complete set of closing quotes.")
    down = result["metric"] == "down"
    verb, noun = ("fell", "decliners") if down else ("rose", "advancers")
    direction = "down" if result["count"] < result["previous_count"] else "up"
    earlier = "unchanged from the prior close" if result["count"] == result["previous_count"] else f"{direction} from {result['previous_count']}"
    target = f"{result['threshold']} or fewer" if down else f"at least {result['threshold']}"
    state = "met" if result["status"] == "met" else "missed"
    return (f"At the {day} close, {result['count']} of the same {total} watchlist names {verb}, {earlier}. "
            f"That {state} our target of {target} {noun}.")
