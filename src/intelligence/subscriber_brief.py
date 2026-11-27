"""Subscriber-facing context drawn from a dated report or an admitted disclosure."""

from datetime import date, datetime, time, timedelta
import re
from sqlite3 import Error as StorageError
from zoneinfo import ZoneInfo

from src.intelligence import company_focus, market_event_desk, weekend_inputs, weekend_store
from src.intelligence.market_brief import DEFENSE_SYMBOLS
from src.intelligence.special_alert_sources import NY, timestamp
from src.intelligence.watchlist_breadth import market_snapshot


NAMES = {**company_focus.COMPANY_NAMES, "SPY": "S&P 500 fund", "QQQ": "Nasdaq-100 fund",
         "IWM": "Russell 2000 fund", "ITA": "U.S. aerospace and defense fund",
         "PEP": "PepsiCo", "VOO": "Vanguard S&P 500 fund", "TLT": "long-term Treasury bond fund"}
PROCUREMENT_QUESTION = ("Defense procurement watch — In the next drone contract announcement from AeroVironment (AVAV) "
                     "or Kratos Defense (KTOS), look for the amount funded at signing. A contract ceiling tells "
                     "readers how large an order could become. The funded amount shows what the buyer has committed so far.")
RESEARCH_QUESTIONS = (
    PROCUREMENT_QUESTION,
    "Defense software watch — At Palantir’s (PLTR) next results, compare government revenue with the prior year. "
    "A newly announced agreement can take several quarters to show up in sales.",
    "Cybersecurity watch — At CrowdStrike’s (CRWD) next update, look for how much recurring subscription revenue "
    "it added. That gives readers a way to judge whether demand for protection is turning into paying customers.",
)
NEXT_SESSION = ("At the next U.S. session — Compare the S&P 500 fund (SPY), which tracks large companies, "
                "with the Russell 2000 fund (IWM), which tracks smaller ones. If both rise, the gains reach "
                "companies of different sizes.")
BAD_SOURCE = (ValueError, TypeError, KeyError, IndexError, OverflowError, AttributeError)


def mover_copy(report, event_context, now, *, archived=False):
    from src.reports.report_quality import split_report_sections

    snapshot = market_snapshot(report)
    day_line = re.search(r"^Quote session: (\d{4}-\d{2}-\d{2})$", snapshot, re.M)
    clock_line = re.search(r"^Quote timestamps \(UTC\): (.+)$", snapshot, re.M)
    if not day_line or not clock_line or "Scope: watchlist regular-session returns versus dated prior closes." not in snapshot.splitlines():
        return ""
    day = date.fromisoformat(day_line[1])
    stamps = [timestamp(v) for v in clock_line[1].split(" to ")]
    local = now.astimezone(NY)
    live = snapshot.startswith("Market Session: Open")
    if (not 0 <= (local.date() - day).days <= 4 or day.weekday() >= 5 or len(stamps) > 2
            or any(not at or at > now or at.astimezone(NY).date() != day
                   or not time(9, 30) <= at.astimezone(NY).time() <= time(16, 20) for at in stamps)
            or stamps[0] > stamps[-1] or live and (archived or local.date() != day or now - stamps[0] > timedelta(minutes=20))
            or not live and not snapshot.startswith("Market Session: Closed")):
        return ""
    # Only the dated movers section and its strongest/weakest lines share this session.
    sections = dict(split_report_sections(report))
    listing = "\n".join(sections.get("Watchlist Movers", []))
    pairs = re.findall(r"^[•-] ([A-Z][A-Z0-9.-]{0,9}): \$[\d,.]+ \(([+-]?\d+(?:\.\d+)?)%\)$", listing, re.M)
    pairs += re.findall(r"^(?:Strongest|Weakest): ([A-Z][A-Z0-9.-]{0,9}) ([+-]?\d+(?:\.\d+)?)%$", snapshot, re.M)
    checked = {(e["source_symbol"], e["reported_move"]) for e in event_context.get("events", []) if e["status"] == "rechecked"}
    prices = {}
    for symbol, raw in pairs:
        value = float(raw)
        if symbol in prices and value != prices[symbol]:
            return ""
        if value and -100 <= value <= 1000 and (abs(value) < market_event_desk.THRESHOLD or (symbol, value) in checked):
            prices[symbol] = value
    groups = []
    used = set()
    for positive in (True, False):
        names = []
        for symbol, change in sorted(prices.items(), key=lambda row: (-abs(row[1]), row[0])):
            issuer = company_focus.issuer(symbol)
            if (change > 0) != positive or issuer in used:
                continue
            label = f"{NAMES[symbol]} ({symbol})" if symbol in NAMES and NAMES[symbol] != symbol else symbol
            names.append(f"{label} {change:+.2f}%")
            used.add(issuer)
            if len(names) == 2:
                break
        if names:
            groups.append(("Higher — " if positive else "Lower — ") + ", ".join(names) + ".")
    if not groups:
        return ""
    when = ("at " + stamps[-1].astimezone(NY).strftime("%I:%M %p ET").lstrip("0")) if live else "at the close"
    next_check = "By the close" if live else "In the next session"
    if len(groups) == 2:
        question = "watch whether the laggards start to catch up with the leaders."
    elif next(iter(prices.values())) > 0:
        question = "watch whether more stocks join these gains."
    else:
        question = "watch whether selling spreads to more stocks."
    return f"Market movers — {day:%B} {day.day}, {when}. " + " ".join(groups) + f" {next_check}, {question}"


def defense_context(item, now):
    from src.intelligence import weekend_theme
    from src.intelligence.defense_coverage import global_policy
    built = timestamp(item["built"])
    story = item["story"]
    published = timestamp(story["published"])
    if (not built or not published or not now - timedelta(days=10) <= published <= built <= now
            or story.get("publisher_symbol") not in DEFENSE_SYMBOLS and not global_policy(story)):
        raise ValueError("Invalid dated defense context")
    if item.get("origin") == "daily":
        from src.intelligence import news_editor, story_analysis
        observed = timestamp(story.get("source_checked_at"))
        if (story.get("decision") != "selected" or not news_editor.primary_source(story)
                or not observed or not published <= observed <= built + timedelta(seconds=60)
                or observed > now or not story.get("source_excerpt")
                or story.get("event_evidence", {}).get("scope") != "original release excerpt"):
            raise ValueError("Historical defense context needs a reviewed original disclosure")
        proof = story_analysis.checked_evidence(story)
        if len(proof["facts"]) < 2 or proof["source_text"] not in story["source_excerpt"]:
            raise ValueError("Historical defense facts differ from the original excerpt")
    else:
        weekend_inputs.checked_story(story, weekend_inputs.window(built), built)
    summary = weekend_theme.summary(story)
    if not summary or len(summary) > 430:
        raise ValueError("Disclosure needs a concise, complete business fact")
    day = published.astimezone(NY)
    return f"Earlier disclosure · {day:%B} {day.day} — {summary}"


def capture(report, events, editions, now):
    context = {"version": 1}
    if not mover_copy(report, events, now):
        for record in editions:
            at = timestamp(record.get("generated_at"))
            if not at or not now - timedelta(days=4) <= at < now:
                continue
            review = record.get("analyst_review") or {}
            old = record.get("research_text", "")
            try:
                checked = market_event_desk.checked_context(review["event_context"], old, at)
                if mover_copy(old, checked, now, archived=True):
                    context["last_close"] = {"report": old, "events": checked, "built": at.isoformat()}
                    break
            except BAD_SOURCE:
                continue
    from src.intelligence import news_editor
    candidates = []
    for edition in editions:
        at = timestamp(edition.get("generated_at"))
        if at and now - timedelta(days=10) <= at < now:
            candidates.extend({"built": at.isoformat(), "story": story, "origin": "daily"}
                              for story in news_editor.selected_stories(edition) if story.get("event_evidence"))
    try:
        weekend = weekend_store.latest()
        if weekend:
            candidates.extend({"built": weekend["generated_at"], "story": story}
                              for story in weekend["inputs"]["stories"])
    except (OSError, StorageError, *BAD_SOURCE):
        pass
    for item in sorted(candidates, key=lambda row: row["story"].get("published") or "", reverse=True):
        try:
            defense_context(item, now)
        except BAD_SOURCE:
            continue
        context["disclosure"] = item
        break
    return context


def apply(context, evidence, report, now):
    if type(context.get("version")) is not int or context["version"] != 1:
        raise ValueError("Unknown subscriber format")
    copy = mover_copy(report, evidence["market_event_context"], now)
    if not copy and (prior := context.get("last_close")):
        at = timestamp(prior["built"])
        if not at or not now - timedelta(days=4) <= at < now:
            raise ValueError("Prior close is outside the subscriber edition window")
        checked = market_event_desk.checked_context(prior["events"], prior["report"], at)
        copy = mover_copy(prior["report"], checked, now, archived=True)
        evidence["subscriber_mover_source"] = "Earlier completed session"
        evidence["source_sections"].append("Earlier completed session")
        if not copy:
            raise ValueError("Prior quotes no longer support the movers")
    evidence["subscriber_movers"] = copy
    evidence["defense_research_question"] = RESEARCH_QUESTIONS[now.astimezone(NY).date().toordinal() % len(RESEARCH_QUESTIONS)]
    if item := context.get("disclosure"):
        evidence["subscriber_disclosure"] = defense_context(item, now)
        evidence["source_sections"].append("Earlier defense disclosure")


def quiet_defense(evidence):
    from src.intelligence.defense_coverage import quiet_copy
    if evidence.get("subscriber_disclosure"):
        return evidence["subscriber_disclosure"]
    if evidence.get("defense_price"):
        return quiet_copy(evidence["defense_price"])
    return evidence["defense_research_question"]


def watch_rows(rows, evidence):
    specific = [row for row in rows if row.get("story_id") or
                (row.get("symbol") and any(source in row["sources"] for source in
                 ("Dated Intel results", "Recent earnings context", "Issuer earnings watch")))]
    if evidence.get("premarket_futures"):
        from src.intelligence import early_futures
        specific.insert(0, {"id": "subscriber_open", "section": "watch", "sources": [early_futures.SOURCE_SECTION],
            "text": "At the open — Compare the Nasdaq-100 fund (QQQ) and the S&P 500 fund (SPY) with their previous closes. "
                    "That will show whether the overnight futures move carried into U.S. stock trading."})
    text = evidence["subscriber_movers"]
    if text:
        first = {"id": "subscriber_movers", "section": "watch", "text": text,
                 "sources": [evidence.get("subscriber_mover_source", "Market Snapshot")]}
        return [first, *specific[:max(0, evidence["reader_limit"] - 1)]]
    return specific[:evidence["reader_limit"]] or [
        {"id": "subscriber_next_session", "section": "watch", "text": NEXT_SESSION, "sources": ["Research coverage policy"]}]


def follow_up(review):
    from src.intelligence import earnings_watch, watchlist_breadth, sector_followup
    evidence = review["evidence"]
    rows = []
    watch = review.get("earnings_watch")
    if earnings_watch.has_answer(watch):
        rows.append(earnings_watch.comparison_text(watch))
        if watch.get("guidance"):
            rows.append(earnings_watch.guidance_source_line(watch))
    if verdict := evidence.get("watchlist_verdict"):
        rows.append(watchlist_breadth.verdict_copy(verdict))
    if answer := evidence.get("intraday_answer"):
        rows.append(answer)
    if sector := evidence.get("sector_verdict"):
        rows.append(sector)
        if review["sector_checkpoint"]["quotes"]:
            rows.append(sector_followup.source_line())
    return rows


def full_report(research, editions, confirmed=()):
    from src.intelligence.earnings_watch import COMPARISON_HEADER
    match = re.search(r"^Generated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+)$", research, re.M)
    if not match:
        return research
    now = datetime.fromisoformat(match[1]).replace(tzinfo=ZoneInfo(match[2]))

    def with_comparison(text):
        marker = "\nWhat Changed Today\n"
        return research.replace(marker, f"\n{COMPARISON_HEADER}\n{text}\n" + marker, 1)

    for record in editions:
        at = timestamp(record.get("generated_at"))
        if not at or at > now or at.astimezone(NY).date() != now.astimezone(NY).date():
            continue
        review = record.get("analyst_review") or {}
        if not review.get("subscriber_context"):
            continue
        rows = follow_up(review)
        if rows:
            clock = at.astimezone(NY).strftime("%I:%M %p ET").lstrip("0")
            return with_comparison(f"As of the {clock} brief.\n" + "\n\n".join(rows))
        break
    from src.intelligence.watchlist_breadth import closing_snapshot, compare
    current = closing_snapshot(market_snapshot(research))
    if current:
        for record in editions:
            if record.get("id") not in confirmed:
                continue
            prior = {"snapshot": market_snapshot(record["research_text"]), "edition_id": record["id"],
                     "generated_at": record["generated_at"]}
            pair = compare(current, prior, now, version=2)
            if pair:
                count = len(pair["symbols"])
                read = (f"Among the {count} symbols quoted at both closes, {pair['previous_down']} fell on "
                        f"{pair['previous_session']} and {pair['down']} fell on {pair['session']}.")
                return with_comparison(read)
    from src.intelligence.daily_brief_analysis import report_evidence
    current_market = report_evidence(research)
    if current_market["session"] == now.astimezone(NY).date().isoformat():
        for record in editions:
            at = timestamp(record.get("generated_at"))
            if (record.get("id") not in confirmed or not at or not at < now
                    or at.astimezone(NY).date() != now.astimezone(NY).date()):
                continue
            prior = report_evidence(record["research_text"])
            if not prior["is_open"] or prior["session"] != current_market["session"]:
                continue
            def last_quote(text):
                times = re.search(r"^Quote timestamps \(UTC\): (.+)$", market_snapshot(text), re.M)
                return timestamp(times[1].split(" to ")[-1]) if times else None
            old_clock, new_clock = last_quote(record["research_text"]), last_quote(research)
            if not old_clock or not new_clock or not old_clock < new_clock <= now:
                continue
            differences = []
            for key, name in (("S&P", "S&P 500"), ("Nasdaq", "Nasdaq Composite")):
                before, after = prior["moves"].get(key), current_market["moves"].get(key)
                if before is not None and after is not None and before != after:
                    differences.append(f"{name} {before:+.2f}% then, {after:+.2f}% now")
            if differences:
                label = at.astimezone(NY).strftime("%I:%M %p ET").lstrip("0")
                read = f"Index moves since the {label} brief, each measured from the prior close. " + ". ".join(differences) + "."
                return with_comparison(read)
            break
    return research
