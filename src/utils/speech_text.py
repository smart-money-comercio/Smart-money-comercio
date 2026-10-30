"""Deterministic English speech formatting; no model or network calls."""

from decimal import Decimal
import re

SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
ORDINAL = {1:"first",2:"second",3:"third",4:"fourth",5:"fifth",6:"sixth",7:"seventh",8:"eighth",9:"ninth",10:"tenth",
           11:"eleventh",12:"twelfth",13:"thirteenth",14:"fourteenth",15:"fifteenth",16:"sixteenth",17:"seventeenth",18:"eighteenth",19:"nineteenth",20:"twentieth",30:"thirtieth"}
ZONES = {"EST":"Eastern Standard Time","EDT":"Eastern Daylight Time","PST":"Pacific Standard Time","PDT":"Pacific Daylight Time","UTC":"U T C"}


def integer(value):
    value = int(value)
    if value < 0: return "minus " + integer(-value)
    if value < 20: return SMALL[value]
    if value < 100: return TENS[value//10] + (" " + SMALL[value%10] if value%10 else "")
    if value < 1000: return SMALL[value//100] + " hundred" + (" " + integer(value%100) if value%100 else "")
    for scale, label in ((10**12,"trillion"),(10**9,"billion"),(10**6,"million"),(1000,"thousand")):
        if value >= scale:
            return integer(value//scale) + " " + label + (" " + integer(value%scale) if value%scale else "")
    raise ValueError("Unsupported speech number")


def number(value):
    raw = format(Decimal(str(value).replace(",", "")), "f")
    whole, _, fraction = raw.partition(".")
    fraction = fraction.rstrip("0")
    negative = raw.startswith("-") and Decimal(raw) != 0
    return ("minus " if negative else "") + integer(abs(int(whole))) + (" point " + " ".join(SMALL[int(char)] for char in fraction) if fraction else "")


def ordinal(value):
    value = int(value)
    return ORDINAL[value] if value in ORDINAL else TENS[value//10] + " " + ORDINAL[value%10]


def normalize(text):
    text = str(text).replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"https?://\S+|(?<!\S)/[A-Za-z][A-Za-z0-9_]*", "", text)
    text = re.sub(r"(?<=\d)[–—](?=\d)", " to ", text)
    text = re.sub(r"\bS&P\s*500\b", "S and P five hundred", text)
    text = re.sub(r"\bRussell\s+2000\b", "Russell two thousand", text)
    text = re.sub(r"\bQ([1-4])\b", lambda m: ORDINAL[int(m[1])] + " quarter", text)
    aliases = {"AI":"A I","IPO":"initial public offering","SEC":"S E C","EPS":"earnings per share",
               "CACI":"C A C I","ASML":"A S M L","GMLRS":"G M L R S","TLT":"T L T","VIX":"volatility index",
               "U.S.":"U S","U.S":"U S"}
    for label in sorted(aliases, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z])"+re.escape(label)+r"(?![A-Za-z])", aliases[label], text)
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    text = re.sub(r"\b("+months+r") (\d{1,2})(?:st|nd|rd|th)?\b", lambda m: m[1]+" "+ordinal(m[2]), text)

    def time(match):
        hour, minute, period, zone = int(match[1]), int(match[2]), match[3].upper(), match[4]
        if not 1 <= hour <= 12 or not 0 <= minute <= 59: raise ValueError("Invalid spoken clock")
        if minute == 0 and hour == 12: result = "noon" if period == "PM" else "midnight"
        else:
            result = integer(hour) + (" oh " + integer(minute) if 0 < minute < 10 else " " + integer(minute) if minute else "")
            result += " in the morning" if period == "AM" else " in the evening" if 6 <= hour < 12 else " in the afternoon"
        return result + (", " + ZONES[zone] if zone else "")
    text = re.sub(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)(?:\s+(EST|EDT|PST|PDT|UTC))?\b", time, text)
    scales = {"k":"thousand", "m":"million", "mn":"million", "b":"billion", "bn":"billion", "t":"trillion"}
    text = re.sub(r"([$€£][\d,]+(?:\.\d+)?)\s*(bn|mn|[kmbt])\b",
                  lambda m: m[1]+" "+scales[m[2].lower()], text, flags=re.I)

    def money(match):
        currency, value, scale = match[1], match[2], match[3]
        singular, plural, fraction = {"$":("dollar","dollars","cent"), "€":("euro","euros","cent"), "£":("pound","pounds","penny")}[currency]
        if scale: return number(value) + " " + scale.lower() + " " + plural
        raw = value.replace(",", ""); whole, _, cents = raw.partition(".")
        if cents and len(cents) <= 2:
            pennies = int(cents.ljust(2, "0"))
            unit = fraction if pennies == 1 else "pence" if fraction == "penny" else "cents"
            return integer(whole) + " " + (singular if int(whole) == 1 else plural) + (" and " + integer(pennies) + " " + unit if pennies else "")
        return number(value) + " " + plural
    text = re.sub(r"([$€£])([\d,]+(?:\.\d+)?)(?:\s+(thousand|million|billion|trillion))?", money, text, flags=re.I)
    text = re.sub(r"([+-]?[\d,]+(?:\.\d+)?)\s*%", lambda m: number(m[1])+" percent", text)
    text = re.sub(r"(?<![A-Za-z0-9])[+-]?\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])", lambda m: number(m[0]), text)
    text = text.replace("&", "and").replace(" · ", ". ").replace("—", ". ").replace("–", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    return text.strip()


def words(text):
    return len(re.findall(r"\b[^\W_]+(?:['’][^\W_]+)*\b", text))
