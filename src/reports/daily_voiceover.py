"""A source-bound spoken edition and read-only ElevenLabs/YouTube handoff."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

from src.utils.speech_text import normalize, words

WPM = 160
MIN_WORDS = 180
MIN_MARKET_WORDS, MAX_MARKET_WORDS = 45, 80


def digest(value):
    return sha256(value.encode()).hexdigest()


def packet(record, report, research):
    return {"report_sha256": digest(report), "research_sha256": digest(research),
            "generated_at": record["generated_at"], "candidates": record["candidates"],
            "analyst_review": record.get("analyst_review"), "company_schedules": record.get("narrated_company_schedules", [])}


def sections(report):
    from src.reports.daily_news_brief import ALL_HEADERS
    groups, current = {}, None
    for line in report.splitlines():
        if line == "Research Notes": break
        if line in ALL_HEADERS: current = line; groups[current] = []; continue
        if current is not None: groups[current].append(line)
    return {key: "\n".join(value).strip() for key, value in groups.items()}


def market_copy(evidence):
    from src.intelligence.market_brief import sentiment, portfolio_lens, story_topics
    moves = evidence["moves"]
    if not evidence.get("session") or not any(key in moves for key in ("S&P", "Nasdaq", "Russell")):
        return ("The broad market picture is incomplete in this edition. Before making a market-wide judgment, we still need dated index and volatility readings. "
                "For a portfolio, the useful next step is to check company updates, upcoming events, and the risks behind each research idea.")
    day = datetime.strptime(evidence["session"], "%Y-%m-%d").strftime("%A, %B %d").replace(" 0", " ")
    clock = "During the " + day + " session" if evidence["is_open"] else "At the close on " + day
    figures = []
    for key, label in (("S&P", "the S&P 500"), ("Nasdaq", "the Nasdaq")):
        if key in moves:
            value = moves[key]
            figures.append(label + (" was unchanged" if value == 0 else f" {'rose' if value > 0 else 'fell'} {abs(value):g} percent"))
    if not figures:
        figures = ["the Russell 2000 " + ("was unchanged" if moves.get("Russell", 0) == 0 else f"{'rose' if moves['Russell'] > 0 else 'fell'} {abs(moves['Russell']):g} percent")]
    mood = sentiment(moves)
    topics = set().union(*(story_topics(story) for story in evidence.get("stories", [])))
    lens = portfolio_lens(moves, topics, mood)
    lens = lens.replace("research case", "case").replace("entry conditions for individual companies", "outlook for individual companies")
    lens = lens.replace("upcoming catalysts", "upcoming company and policy events")
    volatility = (" Volatility " + ("rose." if moves["VIX"] > 0 else "fell." if moves["VIX"] < 0 else "was unchanged.")) if "VIX" in moves else ""
    if moves.get("Oil", 0) >= 1.5:
        figures.append(f"oil rose {moves['Oil']:g} percent")
    figures_text = (", ".join(figures[:-1])+", and "+figures[-1]) if len(figures)>2 else ", while ".join(figures)
    text = clock + ", " + figures_text + "." + volatility
    text += " Our read is " + ("incomplete" if mood == "limited by incomplete coverage" else mood) + ". " + lens
    if words(normalize(text)) + 4 > MAX_MARKET_WORDS:
        text = clock + ", " + figures_text + ". Our read is " + ("incomplete" if mood == "limited by incomplete coverage" else mood) + ". " + lens
    if words(normalize(text)) + 4 < MIN_MARKET_WORDS:
        text += " Watch whether gains or losses spread across more companies in the next session."
    return text


def price_sentence(row, evidence):
    symbol = row["symbol"]
    event = next((event for event in evidence.get("market_event_context", {}).get("events", []) if event["symbol"] == symbol), None)
    if event and event["status"] != "rechecked":
        return row["name"] + "'s unusual price reading still needs confirmation. Check pricing and any stock split before interpreting its business impact."
    value = (row.get("metric") or {}).get("price")
    if value is None and event: value = event["reported_move"]
    if value is None: return ""
    return row['name'] + (" was unchanged" if value == 0 else f" {'rose' if value > 0 else 'fell'} {abs(value):.1f} percent") + " in the quoted session."


def story_copy(story, evidence):
    from src.intelligence.daily_brief_analysis import NAMES
    from src.intelligence.story_analysis import investor_read
    from src.intelligence.broadcast_story import copilot_reveal, company_read
    if story.get("ipo"):
        from src.intelligence.ipo_monitor import checked
        issuer = checked(story)
        milestones = {"plan":"announced plans for an initial public offering", "confidential":"announced a confidential draft submission for an initial public offering",
                      "filing":"filed a public registration for a proposed initial public offering", "amendment":"amended its public registration for a proposed initial public offering",
                      "terms":"announced an indicative price range for its initial public offering", "prospectus":"filed a final prospectus for its initial public offering",
                      "priced":"announced pricing for its initial public offering", "trading planned":"announced a planned start to trading",
                      "trading":"reported the start of trading", "withdrawn":"withdrew its offering"}
        text = issuer["name"] + " " + milestones[story["ipo"]["stage"]] + "."
        if story["ipo"]["stage"] not in {"trading", "withdrawn"}:
            text += " This milestone does not establish that shares are already trading."
        return text + " The investment checks are valuation, losses, funding needs, dilution, and governance."
    if story.get("sec_filing"):
        from src.intelligence.sec_research import checked, narration
        filing = checked(story)
        return filing["issuer"] + " disclosed financing terms in a current SEC report. " + narration(story)
    review = company_read(story) if story["kind"] == "company" else investor_read(story)
    profile = review["evidence"]; fields = {fact["field"]:fact["value"] for fact in profile["facts"]}
    if story["kind"] != "company":
        if profile["event"] == "monetary policy" and profile["stage"] == "rate decision":
            return review["facts"] + " " + review["why"]
        return story["source"] + " reports: " + story["title"].rstrip(".") + ". Review the original release for its scope and implications."
    symbol = story.get("publisher_symbol") or story.get("confirmed_by") or story["symbols"][0]
    name = NAMES.get(symbol, symbol)
    kind, stage = profile["event"], profile["stage"]
    if kind == "contract" and stage not in {"terminated", "cooperation"}:
        purpose = re.search(r"\btask[ -]order to ([^.?!]+)$", story["title"], re.I)
        if purpose and fields.get("contract_ceiling"):
            subject = "a task order"
            for service in ("Army", "Navy", "Air Force"):
                if re.search(r"\b"+service+r"\b", story["title"]): subject = "a U.S. " + service + " task order"; break
            text = name + " announced " + subject + " to " + purpose[1].lower() + "."
            return text + " Its potential value is " + fields["contract_ceiling"] + ". That is a ceiling, not guaranteed revenue."
    if copilot_reveal(story, review):
        return name + " introduced the Copilot harness for multi-model AI work. " + review["why"]
    if fields.get("tested_capability") == "in-flight retargeting" and re.search(r"\bGMLRS\b", story["title"]):
        return name + " reported redirecting a GMLRS rocket in flight during a test. It is a technical milestone; funded orders and production costs will determine the business impact."
    headline = story["title"].rstrip(".")
    if headline.casefold().startswith(name.casefold()+" "):
        headline = name + " " + headline[len(name)+1:][:1].lower() + headline[len(name)+2:]
        text = headline + "."
    else:
        text = "According to " + name + ": " + headline + "."
    if review["facts"]: text += " " + review["facts"]
    if kind == "contract" and stage == "cooperation": text += " Commercial commitments remain the next check."
    else: text += " " + review["why"]
    return text


def focus_copy(row, evidence):
    text = price_sentence(row, evidence)
    contexts = evidence.get("earnings_context", [])
    if contexts and row["symbol"] in {"GOOG", "GOOGL"}:
        from src.intelligence.alphabet_earnings import results_facts
        context = contexts[0]
        labels = {"reported_revenue":"revenue", "reported_operating_margin":"operating margin", "reported_eps":"earnings per share"}
        facts = results_facts(context["text"], context["title"])[:2]
        day = datetime.strptime(context["release_date"], "%Y-%m-%d").strftime("%B %d").replace(" 0", " ")
        values = [re.fullmatch(r"(.+) \((.+)\)",fact["value"]) for fact in facts]
        if not values or any(value is None or value[2]!=values[0][2] for value in values):
            raise ValueError("Spoken earnings context needs a single explicit reporting period")
        text += " For context, its " + day + " results release reported " + values[0][2] + " " + ", and ".join(labels[fact["field"]]+" of "+value[1] for fact,value in zip(facts,values)) + "."
        text += " These dated results do not establish the cause of the price move."
        if context.get("cached_after_failure"): text += " This is previously verified cached context; the latest source access was limited."
    elif text and row["group"] == "market event" and row.get("metric"):
        text += " Check original results and guidance before assigning a business explanation to the move."
    elif text:
        text += " Watch the next company update and whether price and volume support the move."
    return text


def build(record, report, research):
    """Derive a spoken companion only after the original edition passes review."""
    from src.intelligence import news_editor as editor
    from src.intelligence.daily_brief_analysis import validate_review
    from src.reports.daily_news_brief import validate_news_brief
    selected = editor.selected_stories(record)
    review = record["analyst_review"]
    validate_review(review, research, report, selected)
    if not validate_news_brief(report)["passes"]: raise ValueError("Voiceover needs a passing original news brief")
    evidence = review["evidence"]; groups = sections(report); scenes = []; sources = {}
    generated = datetime.fromisoformat(record["generated_at"])
    match = re.search(r"^Generated: .+ (\S+)$", report, re.M)
    local = generated.astimezone(ZoneInfo(match[1]))
    for story in selected:
        if story.get("source_check") != "pass" or not editor.primary_source(story): raise ValueError("Voiceover story lost its original evidence")
        sources[story["id"]] = [{"url":story["url"], "publisher":story["source"], "published_at":story["published"], "verified_at":story["source_checked_at"]}]
    for context in evidence.get("earnings_context", []):
        sources["earnings_GOOG"] = [{"url":url, "publisher":context["source"], "published_at":context["published"], "verified_at":context["observed"]}
            for url in dict.fromkeys((context.get("primary_url", context["url"]), context.get("document_url", context["url"])))]
    calendar_ids = []
    for notice in record.get("narrated_company_schedules", []):
        from src.intelligence.company_schedule import checked_notice
        checked_notice(notice, generated)
        story = notice["source"]; key = "calendar_" + notice["symbol"]
        sources[key] = [{"url":story["url"],"publisher":story["source"],"published_at":story["published"],"verified_at":story["source_checked_at"]}]
        calendar_ids.append(key)

    def add(heading, text, bullets=(), source_ids=()):
        text = normalize(text)
        if not text: return
        scenes.append({"heading":heading, "narration":text, "bullets":list(bullets)[:3], "source_ids":list(source_ids)})

    greeting = re.search(r"^(Hello|Good (?:morning|afternoon|evening))\.$", report, re.M)[0]
    hook = next((row["text"] for row in review["insights"] if row["id"] == "opening_takeaway"), "")
    hook = hook.replace("The takeaway:", "The key takeaway.").replace("in the quoted session", "in the market snapshot")
    add("The Takeaway", greeting+" This is Smart Money for "+local.strftime("%B %d").replace(" 0", " ")+". "+hook,
        ("Source-backed market research", "Edition: "+local.date().isoformat()))
    market = market_copy(evidence)
    add("Market Update", "First, the market. "+market,
        [f"{key}: {evidence['moves'][key]:+.2f}%" for key in ("S&P","Nasdaq","VIX") if key in evidence["moves"]])
    covered = set()
    from src.intelligence.market_brief import story_topics
    from src.intelligence.company_focus import issuer
    for story in sorted(selected, key=editor.news_order):
        defense = "defense" in story_topics(story)
        label = "Defense and Innovation" if defense else "Capital Markets" if story.get("ipo") or story.get("sec_filing") else "Policy and Economy" if story["kind"] == "macro" else "Company News"
        transition = "In defense and innovation. " if defense else "In capital markets. " if label == "Capital Markets" else "On policy. " if story["kind"] == "macro" else "In company news. "
        add(label, transition+story_copy(story,evidence), (story["title"],), (story["id"],))
        covered.update(issuer(symbol) for symbol in story.get("symbols", []))
    for row in evidence.get("company_focus", {}).get("selected", []):
        if issuer(row["symbol"]) in covered or row.get("basis") == "sector context" and row["group"] != "market event": continue
        text = focus_copy(row, evidence)
        if not text: continue
        ids = ["earnings_GOOG"] if evidence.get("earnings_context") and row["symbol"] in {"GOOG","GOOGL"} else []
        add("Companies in Focus", text, (row["role"]+": "+row["name"],), ids)
        covered.add(issuer(row["symbol"]))
    if not any("defense" in story_topics(story) for story in selected):
        add("Defense Watch", "On defense, no fresh development cleared this edition's source checks. Funded orders and production milestones remain the useful checkpoints.", ("Funded orders", "Production milestones"))
    agenda = [paragraph for paragraph in groups.get("What's Ahead", "").split("\n\n")
              if "schedule lists" in paragraph or "has scheduled" in paragraph]
    if agenda:
        text = "Looking ahead. " + " ".join(agenda[:2])
        text = text.replace("The publisher schedule lists", "Watch").replace("A previously checked, cached schedule lists", "A previously checked schedule lists")
        add("What's Ahead", text, agenda[:2], calendar_ids)
    watch = [row["text"] for row in review["insights"] if row["section"] == "watch"]
    signals = []
    for i, text in enumerate(watch):
        label, _, body = text.partition(": ")
        if label.startswith(("Market ", "Staying ", "The ", "Energy ", "IPO ")): label = label[:1].lower()+label[1:]
        signals.append(("First, " if i == 0 else "Second, " if i == 1 else "Finally, ")+label+". "+body)
    add("What We're Watching", "Here are the next checks. "+" ".join(signals), [text.partition(": ")[0] for text in watch])
    editorial = "\n\n".join(row["narration"] for row in scenes)
    add("Closing", "Subscribe to Smart Money for more market research. Research only. Not financial advice.", ("Research only", "Not financial advice"))
    script = "\n\n".join(row["narration"] for row in scenes)
    market_words = words(scenes[1]["narration"])
    quality = {"words":words(script), "editorial_words":words(editorial), "estimated_seconds":round(words(script)*60/WPM,1),
               "words_per_minute":WPM, "market_words":market_words,"market_estimated_seconds":round(market_words*60/WPM,1),
               "passes":words(editorial)>=MIN_WORDS and MIN_MARKET_WORDS<=market_words<=MAX_MARKET_WORDS and 2<=len(scenes)<=14}
    return {"schema":1,"input_sha256":digest(json.dumps(packet(record,report,research),sort_keys=True,ensure_ascii=False,allow_nan=False)),
            "script":script,"script_sha256":digest(script),"segments":scenes,"sources":sources,"quality":quality}


def checked(record, now=None, max_age_hours=8):
    report, research = record.get("report_text"), record.get("research_text")
    if not isinstance(report,str) or not isinstance(research,str) or len(report)>3800 or len(research)>50000:
        raise ValueError("No voice-ready snapshot in this edition; run /rundailyagent after updating")
    if digest(report)!=record.get("report_sha256") or digest(research)!=record.get("research_sha256"):
        raise ValueError("Voiceover source report hash changed")
    if not any(row.get("name")=="Editorial Review" and row.get("status")=="pass" for row in record["stages"]):
        raise ValueError("Voiceover source review did not pass")
    if now is not None:
        generated = datetime.fromisoformat(record["generated_at"])
        if not 0 <= (now-generated).total_seconds() <= max_age_hours*3600:
            raise ValueError("The recorded voiceover edition is stale or future-dated; build a current edition")
    profile = build(record,report,research)
    if profile != record.get("voiceover") or not profile["quality"]["passes"]:
        raise ValueError("Voiceover copy changed or failed its narration checks")
    return profile


def episode(record, now=None, max_age_hours=8):
    profile = checked(record,now,max_age_hours)
    zone = re.search(r"^Generated: .+ (\S+)$",record["report_text"],re.M)[1]
    day = datetime.fromisoformat(record["generated_at"]).astimezone(ZoneInfo(zone)).date().isoformat()
    market = re.search(r"^Market data: (.+)$",record["report_text"],re.M)[1]
    return {"title":"Smart Money Daily Brief | "+day,"date":day,
            "description":"Smart Money financial research. Market data: "+market+". AI narration and illustrative graphics. Research only. Not financial advice.",
            "mode":"draft_review_required","review_required":True,"contains_synthetic_media":True,
            "segments":deepcopy(profile["segments"]),"sources":deepcopy(profile["sources"]),
            "bot_edition_id":record["id"],"bot_report_sha256":record["report_sha256"],"bot_generated_at":record["generated_at"],
            "voiceover_sha256":profile["script_sha256"],"voiceover_quality":deepcopy(profile["quality"])}
