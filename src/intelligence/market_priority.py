"""Reader version 4: observed market pressure precedes secondary source stories."""

import math


def sharp_loss(moves):
    def below(key, threshold):
        value = moves.get(key)
        return type(value) in (int, float) and math.isfinite(value) and value <= threshold
    return below("Nasdaq", -2) or below("S&P", -1.5)


def selloff(evidence):
    return bool(evidence.get("session") and sharp_loss(evidence.get("moves", {})))


def participation_scope(evidence):
    from src.intelligence.reader_brief import _participation_scope
    value = _participation_scope(evidence)
    breadth = evidence["breadth"]
    if breadth["total"] == 1:
        direction = "higher" if breadth["up"] else "lower" if breadth["down"] else "unchanged"
        verb = "is" if evidence["is_open"] else "finished"
        return "The one stock or fund we track " + verb + " " + direction + "."
    if evidence["is_open"]:
        if breadth["up"] == 1:
            value = value.replace(", 1 are higher", ", 1 is higher")
        if breadth["down"] == 1:
            value = value.replace("and 1 lower", "and 1 is lower")
    return value


def opening_source(evidence):
    if selloff(evidence):
        return None
    from src.intelligence.evidence_opening import opening_source as older_source
    return older_source(evidence)


def opening(evidence):
    if not selloff(evidence):
        from src.intelligence.evidence_opening import opening as older_opening
        text = older_opening({**evidence,"reader_version":3})
        if evidence.get("breadth"):
            from src.intelligence.reader_brief import _participation_scope
            text = text.replace(_participation_scope(evidence),participation_scope(evidence))
        return text
    moves = evidence["moves"]
    phrases = []
    for key, label in (("Nasdaq","The Nasdaq"),("S&P","the S&P 500")):
        if key not in moves:
            continue
        value = moves[key]
        if evidence["is_open"]:
            phrase = label + (" is unchanged" if value == 0 else f" is {'down' if value < 0 else 'up'} {abs(value):.2f} percent")
        else:
            phrase = label + (" was unchanged" if value == 0 else f" {'fell' if value < 0 else 'rose'} {abs(value):.2f} percent")
        phrases.append(phrase)
    if phrases and phrases[0].startswith("the "):
        phrases[0] = "The " + phrases[0][4:]
    text = "The takeaway: " + "; ".join(phrases) + " in the quoted session."
    if evidence.get("breadth"):
        text += " " + participation_scope(evidence)
    if evidence.get("business_version") != 2:
        text += " Watch whether selling eases and participation improves; original company results and guidance are the next business checks."
    return text


def watching(evidence):
    from src.intelligence.reader_brief import watching as older_watching, _participation_scope
    context = evidence.get("market_event_context", {})
    events = context.get("events", [])
    if selloff(evidence):
        events = sorted(events, key=lambda row: (row["status"] != "rechecked", -abs(row["reported_move"]), row["symbol"]))
        source = {**evidence,"reader_version":2,"reader_limit":3,"market_event_context":{**context,"events":events}}
        rows = older_watching(source)
        for story in evidence.get("stories",[]):
            profile = story.get("event_evidence",{})
            fields = {row["field"]:row["value"] for row in profile.get("facts",[])}
            if profile.get("schema") == 10 and "next_program_gate" in fields:
                from src.intelligence.daily_brief_analysis import NAMES
                name = NAMES.get(story["publisher_symbol"],story["publisher_symbol"])
                for row in rows:
                    if row["id"] == "watch_business" and row["text"].startswith(name+"'s"):
                        row["text"] = (name+"'s next milestone: Watch for the "+fields["next_program_gate"]+
                            " outcome and updated delivery plans. Those disclosures will help assess development progress and the route to production revenue.")
                break
    else:
        from src.intelligence.evidence_opening import watching as source_watching
        rows = source_watching({**evidence,"reader_version":3,"reader_limit":3})
    if evidence.get("breadth"):
        before, after = _participation_scope(evidence), participation_scope(evidence)
        rows = [{**row,"text":row["text"].replace(before,after)} for row in rows]
    if evidence.get("business_version"):
        from src.intelligence.business_analysis import name
        stories = {story["id"]: story for story in evidence.get("stories", [])}
        for review in evidence.get("business_reviews", []):
            story = stories[review["story_id"]]
            label = name(story)
            for row in rows:
                if row["id"] == "watch_business" and row["text"].startswith(label + "'s"):
                    topic = {"maintenance": "maintenance opportunity", "development": "next milestone"}.get(review["analysis"]["event_class"], "business follow-through")
                    row["text"] = label + "'s " + topic + ": " + review["analysis"]["decision_test"]
    if evidence.get("business_version") == 2:
        rows = concise_checks(evidence, rows, events[0] if events else None)
    return rows[:evidence.get("reader_limit",3)]


def concise_checks(evidence, rows, event):
    """Keep the participation test distinct from the observed count in the lead."""
    breadth = evidence.get("breadth")
    if breadth:
        scope = participation_scope(evidence)
        if scope in opening(evidence):
            for row in rows:
                if row["id"] == "watch_participation":
                    row["text"] = row["text"].replace(scope + " ", "", 1)

    from src.intelligence.business_analysis import name
    stories = {story["id"]: story for story in evidence.get("stories", [])}
    point = opening_source(evidence) or {}
    reviews = [row for row in evidence.get("business_reviews", [])
               if row["analysis"]["event_class"] in {"commercial rollout", "production milestone"}]
    earnings_story = any(story.get("materiality") in {"earnings", "guidance"} and story.get("event_evidence", {}).get("facts")
                         for story in stories.values())
    if not reviews or earnings_story or any("Recent earnings context" in row["sources"] for row in rows):
        return rows
    review = min(reviews, key=lambda row: (row["story_id"] not in point.get("story_ids", []), row["story_id"]))
    story = stories[review["story_id"]]
    label = "AMD's server rollout" if story.get("publisher_symbol") == "AMD" else name(story) + "'s production economics"
    test = {"id": "watch_business", "section": "watch", "sources": ["Verified story decisions"],
            "text": label + ": " + review["analysis"]["decision_test"]}
    displaced = {"watch_business", "watch_results"}
    if event and event["status"] == "rechecked":
        displaced.add("watch_event")
    rows = [row for row in rows if row["id"] not in displaced]
    rows.insert(1 if rows and rows[0]["id"] == "watch_participation" else 0, test)
    return rows
