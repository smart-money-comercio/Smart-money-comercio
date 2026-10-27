"""Conservative financial-table and disclosure evidence from an IPO prospectus."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from html.parser import HTMLParser
import json
import re

from src.intelligence.story_analysis import VisibleText


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.depth = 0; self.tables = []; self.rows = []; self.row = []; self.cell = None; self.span = 1; self.bad = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.rows, self.bad = [], False
            else:
                self.bad = True
        if self.depth == 1 and tag == "tr":
            self.row = []
        if self.depth == 1 and tag in {"td", "th"}:
            values = dict(attrs); self.cell = []
            try:
                self.span = int(values.get("colspan", 1))
                if not 1 <= self.span <= 24 or int(values.get("rowspan", 1)) != 1:
                    self.bad = True; self.span = 1
            except ValueError:
                self.bad = True; self.span = 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.depth == 1 and tag in {"td", "th"} and self.cell is not None:
            self.row.extend([" ".join("".join(self.cell).split())[:220]] * self.span); self.cell = None
        if self.depth == 1 and tag == "tr":
            self.rows.append(self.row)
        if tag == "table" and self.depth:
            self.depth -= 1
            if self.depth == 0 and not self.bad and len(self.rows) <= 80 and all(len(row) <= 30 for row in self.rows):
                self.tables.append(self.rows)


def metric(label: str) -> str:
    label = re.sub(r"\(\d+\)", "", label).strip().lower()
    if label in {"revenue", "total revenue", "net revenue"}: return "revenue"
    if label == "net loss": return "net_loss"
    if label == "operating loss": return "operating_loss"
    if re.fullmatch(r"net cash (?:used in|provided by|provided by \(used in\)|used in \(provided by\)) operating activities", label): return "operating_cash_flow"
    if label.startswith("change in fair value of") and any(word in label for word in ("convertible", "derivative", "safe")): return "financing_fair_value_change"
    return ""


def number(raw: str) -> str | None:
    raw = raw.replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"(?:-?\d+(?:\.\d+)?|\(\d+(?:\.\d+)?\))", raw):
        return None
    try:
        value = Decimal(raw.strip("()")) * (-1 if raw.startswith("(") else 1)
        return str(value) if value.is_finite() else None
    except InvalidOperation:
        return None


def table_facts(rows: list[list[str]]) -> list[dict]:
    flat = " ".join(cell for row in rows[:5] for cell in row)
    if re.search(r"\bpro\s*forma\b", flat, re.I):
        return []
    units = re.findall(r"\bin (millions|thousands)\b", flat, re.I)
    if len(set(word.lower() for word in units)) != 1:
        return []
    unit = units[0].lower()
    if not any("$" in cell for row in rows for cell in row) or re.search(r"(?:CAD|HKD|CNY|EUR|Canadian dollars|Hong Kong dollars|C\$|HK\$)", flat, re.I):
        return []
    periods = {}
    for index, row in enumerate(rows[:8]):
        for column, text in enumerate(row):
            year = re.fullmatch(r"20\d{2}", text)
            if not year:
                continue
            context = " ".join(previous[column] for previous in rows[max(0,index-3):index] if column < len(previous))
            matches = re.findall(r"\b(Year|Three Months|Six Months|Nine Months) Ended (January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2})", context, re.I)
            if len(set(matches)) == 1:
                scope, month, day = matches[0]
                periods[column] = {"year": int(year[0]), "scope": scope.lower(), "period": f"{scope} ended {month} {day}, {year[0]}"}
    facts = []
    for row in rows:
        if not row or not metric(row[0]):
            continue
        for column, period in periods.items():
            value = number(row[column]) if column < len(row) else None
            if value is not None:
                facts.append({"field": metric(row[0]), **period, "value": value, "unit": unit, "currency": "$",
                              "column": column, "row_label": row[0], "source_value": row[column]})
    return facts


def evidence(raw: bytes) -> dict:
    text = raw[:1_000_000].decode("utf-8", "replace")
    parser = Tables(); parser.feed(text)
    tables = []
    for rows in parser.tables:
        if table_facts(rows):
            candidate = tables + [rows]
            if len(json.dumps(candidate).encode()) <= 16_000:
                tables = candidate
            if len(tables) >= 3: break
    visible = VisibleText(); visible.feed(text)
    plain = " ".join("".join(visible.parts).split())
    passages = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z“])", plain):
        if not 40 <= len(sentence) <= 550:
            continue
        if re.search(r"\bLong-Term Benefit Trust\b", sentence, re.I) and re.search(r"\b(appoint|elect|select)\w*\b", sentence, re.I) and re.search(r"\b(board|directors)\b", sentence, re.I):
            passages.append({"field": "governance", "text": sentence})
        if (re.search(r"\b(single customer|largest customer|one customer)\b", sentence, re.I)
                and re.search(r"\d+(?:\.\d+)?%", sentence) and re.search(r"\brevenue\b", sentence, re.I)
                and re.search(r"\b20\d{2}\b", sentence) and not re.search(r"\b(will|expect|project|may|could)\b", sentence, re.I)):
            passages.append({"field": "customer_concentration", "text": sentence})
        if len(passages) >= 3: break
    return {"schema": 1, "tables": tables, "passages": passages, "prefix_sha256": hashlib.sha256(raw[:1_000_000]).hexdigest()}


def analyze(source: dict) -> dict:
    if (not isinstance(source, dict) or source.get("schema") != 1 or not isinstance(source.get("tables"), list)
            or not isinstance(source.get("passages"), list) or len(source["tables"]) > 3 or len(source["passages"]) > 3
            or not re.fullmatch(r"[a-f0-9]{64}", str(source.get("prefix_sha256", "")))
            or len(json.dumps(source).encode()) > 22_000):
        raise ValueError("Invalid IPO financial evidence")
    for passage in source["passages"]:
        if (not isinstance(passage, dict) or set(passage) != {"field", "text"}
                or passage["field"] not in {"governance", "customer_concentration"}
                or not isinstance(passage["text"], str) or not 40 <= len(passage["text"]) <= 550):
            raise ValueError("Invalid IPO disclosure passage")
    facts = []
    for rows in source["tables"]:
        if not isinstance(rows, list) or len(rows) > 80 or any(not isinstance(row, list) or len(row) > 30 or any(not isinstance(cell, str) or len(cell) > 220 for cell in row) for row in rows):
            raise ValueError("Invalid IPO financial table")
        facts += table_facts(rows)
    by_key = {}
    for fact in facts:
        key = (fact["field"], fact["period"])
        by_key.setdefault(key, {})[fact["value"] + fact["unit"]] = fact
    facts = [next(iter(values.values())) for values in by_key.values() if len(values) == 1]
    return {"facts": facts[:50], "passages": source["passages"],
            "source_sha256": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()}


def dollars(fact: dict) -> str:
    value = abs(Decimal(fact["value"])) * (1_000_000 if fact["unit"] == "millions" else 1000)
    scale, label = (Decimal(1_000_000_000), "billion") if value >= 1_000_000_000 else (Decimal(1_000_000), "million")
    return "$" + str((value / scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)).rstrip("0").rstrip(".") + " " + label


def narration(analysis: dict) -> str:
    annual = [row for row in analysis["facts"] if row["scope"] == "year"]
    revenues = sorted((row for row in annual if row["field"] == "revenue"), key=lambda row: row["year"])
    if not revenues:
        return ""
    latest = revenues[-1]
    text = f"The filing reports {latest['year']} revenue of {dollars(latest)}"
    if (len(revenues) > 1 and revenues[-2]["year"] == latest["year"]-1
            and revenues[-2]["period"].rsplit(",", 1)[0] == latest["period"].rsplit(",", 1)[0]
            and revenues[-2]["unit"] == latest["unit"]):
        text += f", versus {dollars(revenues[-2])} in {revenues[-2]['year']}"
        if Decimal(revenues[-2]["value"]) > 0:
            growth = (Decimal(latest["value"]) / Decimal(revenues[-2]["value"]) - 1) * 100
            text += f", a {abs(growth):.1f} percent {'increase' if growth >= 0 else 'decrease'}"
    text += "."
    losses = {row["field"]: row for row in annual if row["period"] == latest["period"]}
    if "operating_loss" in losses:
        text += f" Its {latest['year']} operating loss was {dollars(losses['operating_loss'])}."
    if "net_loss" in losses:
        text += f" Reported net loss was {dollars(losses['net_loss'])}; this is not an operating-cash-flow measure."
    if "financing_fair_value_change" in losses:
        row = losses['financing_fair_value_change']
        text += f" The filing separately records a {dollars(row)} financing-related fair-value {'loss' if Decimal(row['value']) < 0 else 'gain'}."
    cash = losses.get("operating_cash_flow")
    if cash:
        text += f" Operating activities {'used' if Decimal(cash['value']) < 0 else 'provided'} {dollars(cash)} in {latest['year']}."
    else:
        text += " Operating cash burn is not established by this excerpt."
    if any(row["field"] == "governance" for row in analysis["passages"]):
        text += " The filing describes trust-based board appointment rights; review the full governance conditions."
    concentration = next((row for row in analysis["passages"] if row["field"] == "customer_concentration"), None)
    if concentration:
        text += " The filing discloses customer concentration; review the dated revenue exposure in the original prospectus."
    return text
