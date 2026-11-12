"""Financial facts from a directly attributed original order announcement."""

from decimal import Decimal
import re

from src.intelligence.original_disclosures import sentences


MONEY = r"\$\d+(?:,\d{3})*(?:\.\d+)?\s+(?:billion|million|thousand)\b"
VALUE = r"(?P<limit>up to\s+)?(?P<amount>" + MONEY + r")"
ORDER = r"(?P<instrument>(?:(?:initial|follow-on|international|direct commercial sales|purchase|customer)\s+){0,4}order)\b"
OBJECT = r"(?:an?|the)\s+(?:(?:landmark|new|firm|binding)\s+){0,3}"
VALUE_FIRST = re.compile(OBJECT + VALUE + r"\s+" + ORDER, re.I)
ORDER_FIRST = re.compile(OBJECT + ORDER + r"\s+(?:valued at|worth|with a stated value of)\s+" + VALUE, re.I)
HEADLINE = re.compile(r"\b(?:award(?:ed|s)?|announc(?:ed|es)|receiv(?:ed|es)|wins?|won|secur(?:ed|es))\b.{0,125}\border\b", re.I)
DATELINE = re.compile(r"^[A-Z][A-Za-z.,\s-]{0,80}(?:[–—-]\s*)?\(?[A-Za-z]+\.? \d{1,2},? 20\d{2}\)?\s*[–—-]\s*", re.I)
UNSUPPORTED = re.compile(r"\b(?:not|no|without|previously|last year|ago|propos\w*|expect\w*|intends?|plans?|seeks?|bids?|could|might|would|may|rumou?r\w*|"
                         r"non[ -]?binding|letter of intent|subject to|conditional on|pending|options?|cancel\w*|terminat\w*|revok\w*)\b", re.I)
RECEIVED = r"(?:(?:has\s+been|was)\s+awarded|(?:has\s+)?(?:received|secured|won))"


def extract(story, text):
    title = story["title"]
    symbol = story.get("publisher_symbol")
    if story.get("kind") != "company" or not symbol or not HEADLINE.search(title) or UNSUPPORTED.search(title):
        return None

    from src.intelligence.news_editor import ALIASES
    names = "|".join(re.escape(name) for name in sorted(ALIASES.get(symbol, [symbol]), key=len, reverse=True))
    subject = re.compile(r"^(?:" + names + r")(?:,?\s+(?:Inc\.|Corporation|Corp\.|Ltd\.|plc))?"
                         r"(?:\s*\([^()\n]{1,80}\)){0,3},?\s+(?:today\s+)?"
                         r"(?P<verb>announced(?:\s+(?:that\s+)?it\s+" + RECEIVED + r")?|" + RECEIVED + r")\s+", re.I)
    matches = {}
    for sentence in sentences(text):
        if sentence.casefold() == title.casefold() or UNSUPPORTED.search(sentence):
            continue
        row = DATELINE.sub("", sentence, count=1)
        actor = subject.match(row)
        if not actor:
            continue
        award = VALUE_FIRST.match(row, actor.end()) or ORDER_FIRST.match(row, actor.end())
        if not award or len(re.findall(MONEY, row, re.I)) != 1:
            continue
        tail = row[award.end():]
        allowed_tail = r"^(?:$|[.,;]|\s+(?:for|from)\b)"
        if actor["verb"].casefold() == "announced":
            allowed_tail = r"^(?:$|[.,;]|\s+(?:for its|from)\b)"
        if not re.match(allowed_tail, tail, re.I):
            continue
        amount = award["amount"].lower()
        if Decimal(amount.split()[0][1:].replace(",", "")) <= 0:
            continue
        instrument = award["instrument"].lower().replace("direct commercial sales ", "").replace("customer ", "")
        basis = "ceiling" if award["limit"] else "stated value"
        proof = row[:award.end()]
        matches.setdefault((amount, instrument, basis), proof)
    if len(matches) != 1:
        return None
    (amount, instrument, basis), proof = next(iter(matches.items()))
    headline_amounts = [value.lower() for value in re.findall(MONEY, title, re.I)]
    if (headline_amounts and headline_amounts != [amount]) or (re.search(r"\bup to\b", title, re.I) and basis != "ceiling"):
        return None
    value = "up to " + amount if basis == "ceiling" else amount
    return [
        {"field": "order_value", "value": value, "basis": basis, "evidence": proof},
        {"field": "order_type", "value": instrument, "evidence": proof},
    ]


def summary(profile, name, *, day=None):
    fields = {row["field"]: row for row in profile["facts"]}
    instrument = fields["order_type"]["value"]
    value = fields["order_value"]
    article = "an" if instrument.startswith(("international", "initial")) else "a"
    when = f" in its {day} announcement" if day else ""
    return f"{name} reported {article} {instrument} worth {value['value']}{when}."


def review(profile, name):
    return {"facts": summary(profile, name),
            "why": "Execution costs and the pace of deliveries will shape what the order contributes to earnings.",
            "watch": "Look for a delivery timetable and an update to revenue or margin guidance.",
            "evidence": profile}
