"""Reader version 3: observed market conditions and admitted disclosure facts."""

from datetime import datetime
import re

from src.intelligence.daily_brief_analysis import NAMES


def opening_source(evidence):
    from src.intelligence.story_analysis import checked_evidence
    from src.intelligence.news_editor import primary_source
    points = []
    for story in evidence.get("stories", []):
        if story.get("decision") != "selected" or story.get("source_check") != "pass" or not primary_source(story):
            continue
        profile = checked_evidence(story)
        fields = {row["field"]:row["value"] for row in profile["facts"]}
        name = NAMES.get(story.get("publisher_symbol"), story.get("publisher_symbol", story["source"]))
        if evidence.get("disclosure_version", 0) >= 2 and story.get("source") == "Eaton Newsroom":
            name = "Eaton"
        text, watch, priority = "", "", 9
        if profile["event"] == "monetary policy" and profile["stage"] == "rate decision" and "policy_target_range" in fields:
            from src.intelligence.story_analysis import investor_read
            text = investor_read(story)["facts"]
            watch, priority = "Watch inflation readings and company financing plans.", 0
        elif profile["schema"] == 9 and "refunding_offering" in fields and "refunding_maturities" in fields:
            text = ("Treasury's refunding plan would raise " + fields["refunding_new_cash"] + " in new cash." if "refunding_new_cash" in fields else
                    "Treasury plans to offer " + fields["refunding_offering"] + " to refinance " + fields["refunding_maturities"] + " in maturing debt.")
            watch, priority = "Watch auction demand and yields for a check on financing conditions.", 1
        elif profile["schema"] == 11 and "gasoline_yield_average" in fields:
            row = next(row for row in profile["facts"] if row["field"] == "gasoline_yield_average")
            text = "EIA reported U.S. refinery gasoline yields averaging " + row["comparison"].replace("%"," percent") + " from " + row["period"] + "."
            watch, priority = "Check current product inventories and refinery margins for a more recent business read.", 2
        elif profile["schema"] == 10 and {"program_name", "program_stage", "development_test"} <= fields.keys():
            text = name + " reported a flight-test milestone for its " + fields["program_stage"] + " " + fields["program_name"] + "."
            watch = ("The next disclosed program gate is " + fields["next_program_gate"] + "." if "next_program_gate" in fields else
                     "Watch further test results and funded delivery plans.")
            priority = 3
        elif profile["schema"] == 12:
            from src.intelligence.disclosure_details import summary, review
            from src.intelligence.original_disclosures import sentences
            text = sentences(summary(profile, name))[0]
            watch = review(profile)["watch"]
            if evidence.get("disclosure_version", 0) >= 2:
                text = name + " has a new aircraft-maintenance designation."
                watch = "The commercial follow-through matters next."
            priority = 3
        elif evidence.get("business_version", 0) >= 2 and profile["schema"] == 14:
            if profile["stage"] == "available":
                text = "Server shipments put AMD's new EPYC launch into commercial rollout."
                priority = 3
            else:
                text = "Lockheed Martin reported GMLRS delivery number " + fields["delivery_milestone"] + "."
                priority = 4
        elif profile["schema"] == 15:
            from src.intelligence.order_awards import summary
            text = summary(profile, name)
            watch, priority = "Look for delivery timing and any change to revenue guidance.", 2
        elif profile["event"] == "earnings":
            field = next((key for key in ("reported_revenue", "reported_sales", "reported_net_sales") if key in fields), None)
            match = re.fullmatch(r"(\$[\d,.]+\s*(?:billion|million)?) \(([^()]+)\)", fields[field]) if field else None
            if match:
                period = match[2].lower().removesuffix(", reported")
                text = name + " reported " + field.removeprefix("reported_").replace("_", " ") + " of " + match[1] + " for " + period + "."
                watch, priority = "Compare management's guidance with margins and cash generation.", 0
        elif profile["schema"] == 8 and profile["facts"]:
            from src.intelligence.original_disclosures import summarize, sentences
            summary = summarize(story, profile, name, for_speech=True)
            if summary:
                text = sentences(summary)[0]
                watch = ("Watch funded work, delivery costs and revenue timing." if profile["event"] == "contract" else
                         "Watch paying customer commitments and deployment progress.")
                priority = 2 if profile["event"] == "contract" else 4
        if text:
            points.append((priority, -datetime.fromisoformat(story["published"].replace("Z", "+00:00")).timestamp(), story["id"],
                           {"text":text, "watch":watch, "story_ids":[story["id"]]}))
    return min(points, key=lambda value: value[:3])[3] if points else None


def market_observation(evidence):
    moves, opened = evidence["moves"], evidence["is_open"]
    breadth = evidence.get("breadth")
    total_scope = ""
    if breadth and (breadth["down"] == breadth["total"] or breadth["up"] == breadth["total"]):
        from src.intelligence.reader_brief import _participation_scope
        total_scope = " " + _participation_scope(evidence)
    indexes = [(key, moves[key]) for key in ("S&P", "Nasdaq", "Russell") if key in moves]
    if len(indexes) < 2:
        return "Market coverage is incomplete." + total_scope
    same_up, same_down = all(value > 0 for _, value in indexes), all(value < 0 for _, value in indexes)
    if len(indexes) == 3:
        if same_up:
            text = "All three major indexes are higher in the quoted session." if opened else "All three major indexes rose in the completed session."
        elif same_down:
            text = "All three major indexes are lower in the quoted session." if opened else "All three major indexes fell in the completed session."
        elif all(value == 0 for _, value in indexes):
            text = "The three quoted major indexes are unchanged."
        elif moves["Nasdaq"] < 0 < moves["Russell"]:
            text = ("The Nasdaq is lower while the Russell index is higher." if opened else
                    "The Nasdaq fell while the Russell index rose.")
        elif moves["Russell"] < 0 < moves["Nasdaq"]:
            text = ("The Nasdaq is higher while the Russell index is lower." if opened else
                    "The Nasdaq rose while the Russell index fell.")
        else:
            text = "The quoted major indexes are mixed." if opened else "The major indexes ended the quoted session mixed."
    else:
        names = " and ".join({"S&P":"S&P 500", "Nasdaq":"Nasdaq", "Russell":"Russell index"}[key] for key, _ in indexes)
        text = names + (" are higher." if opened else " rose in the completed session.") if same_up else (
               names + (" are lower." if opened else " fell in the completed session.") if same_down else
               "The available index readings are mixed.")
    if total_scope:
        text += total_scope
    elif same_up and breadth and breadth["down"] > breadth["up"]:
        text += " Most names in our tracked group are still lower." if opened else " Most names in our tracked group still finished lower."
    return text


def opening(evidence):
    point = opening_source(evidence)
    version = evidence.get("business_version", 0)
    concise = version >= 2
    market = market_observation(evidence)
    breadth = evidence.get("breadth")
    story_first = version >= 5 and not (breadth and breadth["down"] == breadth["total"])
    if point:
        if story_first:
            return "The takeaway: " + point["text"] + " " + market
        return "The takeaway: " + market + " " + point["text"] + ("" if concise else " " + point["watch"])
    from src.intelligence.company_earnings import matching
    events = evidence.get("market_event_context", {}).get("events", [])
    checked = next((row for row in events if row["status"] == "rechecked"), None)
    if checked and matching(evidence.get("earnings_context", []), checked["symbol"]):
        from src.intelligence.reader_brief import opening as older_opening
        return older_opening({**evidence,"reader_version":2})
    text = "The takeaway: " + market
    if checked:
        move = checked["reported_move"]
        mover = NAMES.get(checked["symbol"], checked["symbol"]) + f" {'rose' if move > 0 else 'fell'} {abs(move):.1f} percent."
        if story_first:
            return "The takeaway: " + mover + " " + market
        text += " " + mover
        if concise:
            return text
        text += " Compare the move with original results and guidance to assess the business outlook."
        if move < 0 and breadth and breadth["down"] > breadth["up"]:
            text += " Watch for selling to ease across the names we track."
        elif move > 0 and breadth and breadth["up"] > breadth["down"]:
            text += (" Watch whether those gains hold in the next session." if evidence.get("disclosure_version", 0) >= 1 and not evidence["is_open"] else
                     " Watch whether those gains hold in this group.")
    elif not concise:
        text += " Watch participation across the names we track and the next company results."
    return text


def watching(evidence):
    from src.intelligence.reader_brief import story_watch, watching as older_watching
    from src.intelligence.company_earnings import matching
    rows = older_watching({**evidence,"reader_version":2,"reader_limit":3})
    financial = any(story.get("materiality") in {"earnings", "guidance"} and story.get("event_evidence", {}).get("facts")
                    for story in evidence.get("stories", []))
    event = next(iter(evidence.get("market_event_context", {}).get("events", [])), None)
    context = matching(evidence.get("earnings_context", []), event["symbol"]) if event else None
    if not financial and not context:
        for story in evidence.get("stories", []):
            profile = story.get("event_evidence", {})
            fields = {row["field"]:row["value"] for row in profile.get("facts", [])}
            if profile.get("schema") == 12:
                from src.intelligence.disclosure_details import review
                name = NAMES.get(story.get("publisher_symbol"), story["source"])
                label = name + "'s maintenance opportunity"
                text = label + ": " + review(profile)["watch"]
                if evidence.get("disclosure_version", 0) >= 2:
                    text = label + ": Watch for a disclosed service-order value and delivery timetable. Those details would help establish the scale and timing of the opportunity."
                rows = [row for row in rows if row["id"] not in {"watch_business", "watch_event"}]
                rows.insert(1 if rows else 0, story_watch(story, text, evidence))
                break
            if profile.get("schema") != 10 or "next_program_gate" not in fields:
                continue
            name = NAMES.get(story["publisher_symbol"],story["publisher_symbol"])
            business = next((row for row in rows if row["id"] == "watch_business"), None)
            if business and not business["text"].startswith(name + "'s"):
                break
            text = (name + "'s next milestone: Watch for the " + fields["next_program_gate"]
                    + " outcome and updated delivery plans. Those disclosures will help assess development progress and the route to production revenue.")
            rows = [row for row in rows if row["id"] not in {"watch_business", "watch_event"}]
            rows.insert(1 if rows else 0, story_watch(story, text, evidence))
            break
    if evidence.get("disclosure_version", 0) >= 1:
        for row in rows:
            row["text"] = row["text"].replace("Advanced Micro Devices's", "AMD's")
    return rows[:evidence.get("reader_limit",3)]
