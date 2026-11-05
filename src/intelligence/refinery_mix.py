"""Dated U.S. refinery product yields from an admitted original EIA report."""

from calendar import monthrange
from datetime import date
import re
from urllib.parse import urlsplit, parse_qs

from src.intelligence.special_alert_sources import timestamp


MONTHS = "January February March April May June July August September October November December".split()
MONTH = "(?:" + "|".join(MONTHS) + ")"
UNCERTAIN = r"\b(?:not|no|could|may|might|would|forecast|expects?|projected|hypothetical|previously)\b"
REGIONAL = r"\b(?:California|Gulf Coast|West Coast|East Coast|Europe\w*|Asia\w*|China|Chinese|India\w*|Canada|Canadian|UK|British|regional|selected refineries)\b"


def applicable(story):
    try:
        parts = urlsplit(story.get("url", ""))
        original = (parts.scheme == "https" and parts.hostname in {"eia.gov","www.eia.gov"}
                    and not parts.username and not parts.password and parts.port in (None,443)
                    and parts.path.lower() == "/todayinenergy/detail.php"
                    and len(parse_qs(parts.query).get("id",[])) == 1
                    and re.fullmatch(r"\d+",parse_qs(parts.query)["id"][0]))
    except ValueError:
        return False
    title = story.get("title", "")
    return bool(story.get("source") == "EIA" and original and re.search(r"\brefiner\w*\b",title,re.I)
                and re.search(r"\b(?:gasoline|distillates?|jet fuel)\b",title,re.I)
                and re.search(r"\b(?:shift\w*|yields?|product mix)\b",title,re.I))


def product_facts(story, text):
    if not applicable(story):
        return []
    from src.intelligence.original_disclosures import sentences
    published = timestamp(story.get("published"))
    if published is None:
        raise ValueError("EIA product facts need an original zoned publication clock")
    rows = sentences(text)
    if not any(re.search(r"\b(?:U\.S\.|United States) refin(?:ery|eries|ers|ing)\b",row)
               and not re.search(UNCERTAIN,re.sub(r"\bMay\b","[month]",row),re.I)
               and not re.search(REGIONAL,row,re.I) for row in rows):
        return []
    facts = []

    def period_end(month,year):
        number = MONTHS.index(month.title())+1
        value = date(int(year),number,monthrange(int(year),number)[1])
        return value if value <= published.date() else None

    def add(field, matches):
        if len({row["value"] for row in matches}) == 1:
            facts.append({"field":field,**matches[0]})

    through, gasoline, first_jet, jet_floor, incentive = [], [], [], [], []
    for row in rows:
        uncertainty = re.sub(r"\bMay\b", "[month]", row)
        if len(row)>650 or re.search(UNCERTAIN,uncertainty,re.I) or re.search(REGIONAL,row,re.I):
            continue
        match = re.search(r"\bPetroleum Supply Monthly.{0,180}?\bdata through ("+MONTH+r") (20\d{2})\b",row)
        if match and period_end(match[1],match[2]):
            through.append({"value":match[1]+" "+match[2],"period_end":f"{int(match[2]):04d}-{MONTHS.index(match[1])+1:02d}",
                            "evidence":row,"status":"latest measurement coverage stated by the publisher"})
        match = re.search(r"\bFrom ("+MONTH+r") through ("+MONTH+r") (20\d{2}), refinery yields of (?:motor )?gasoline have averaged "
                          r"(less than|below|more than|above|at least|at most)?\s*(\d+(?:\.\d+)?)%"
                          r"(?!\s*(?:[-–—]|(?:to|or|and)\s+(?:(?:less than|more than|above|below|at least|at most)\s+)?\d))",row)
        if match and MONTHS.index(match[1])<=MONTHS.index(match[2]) and period_end(match[2],match[3]) and 0<float(match[5])<=100:
            comparator = match[4] or ""
            comparison = (comparator+" " if comparator else "")+match[5]+"%"
            span = match[1]+" through "+match[2]+" "+match[3]
            gasoline.append({"value":comparison+" ("+span+")","comparison":comparison,"period":span,
                "period_end":f"{int(match[3]):04d}-{MONTHS.index(match[2])+1:02d}","evidence":row,
                "geography":"United States","unit":"refinery product yield, percent","status":"dated reported average; not a current fuel price"})
        match = re.search(r"\bU\.S\. refinery fleet exceeded an average jet fuel yield of (\d+(?:\.\d+)?)% for the first time in ("+MONTH+r") (20\d{2})\b",row)
        if match and period_end(match[2],match[3]) and 0<float(match[1])<=100:
            first_jet.append({"value":"above "+match[1]+"% ("+match[2]+" "+match[3]+")","threshold":match[1],
                "period_end":f"{int(match[3]):04d}-{MONTHS.index(match[2])+1:02d}","evidence":row,"status":"dated first reported exceedance"})
        match = re.search(r"\bfleetwide average jet fuel yield has remained (at or above|above|at least) (\d+(?:\.\d+)?)% through "
                          r"the latest Petroleum Supply Monthly data for ("+MONTH+r") (20\d{2})\b",row)
        if match and period_end(match[3],match[4]) and 0<float(match[2])<=100:
            jet_floor.append({"value":match[1]+" "+match[2]+"% through "+match[3]+" "+match[4],
                "comparison":match[1]+" "+match[2]+"%","threshold":match[2],"period":match[3]+" "+match[4],
                "period_end":f"{int(match[4]):04d}-{MONTHS.index(match[3])+1:02d}","evidence":row,"status":"dated reported product-yield floor"})
        match = re.search(r"\bhigh refinery margins for distillate fuel oil and jet fuel have contributed to shifts in the refinery yields of major products in (20\d{2})\b",row)
        if match and int(match[1])<=published.year:
            incentive.append({"value":"higher distillate and jet-fuel margins encouraged the reported product shift",
                              "evidence":row,"status":"EIA interpretation of the dated production mix"})
    add("measurement_coverage",through)
    add("gasoline_yield_average",gasoline)
    values = {row["field"]:row for row in facts}
    if not {"measurement_coverage","gasoline_yield_average"}<=values.keys():
        return []
    if values["gasoline_yield_average"]["period_end"]>values["measurement_coverage"]["period_end"]:
        return []
    first_jet = [row for row in first_jet if row["period_end"]<=values["measurement_coverage"]["period_end"]]
    add("jet_fuel_first_exceeded",first_jet)
    if any(row["field"]=="jet_fuel_first_exceeded" for row in facts) and len({r["threshold"] for r in jet_floor})==1:
        threshold = first_jet[0]["threshold"]
        compatible = [r for r in jet_floor if r["threshold"]==threshold and
                      first_jet[0]["period_end"]<=r["period_end"]<=values["measurement_coverage"]["period_end"]]
        add("jet_fuel_yield_floor",compatible)
    add("margin_incentive",incentive)
    return facts


def material(facts):
    return {"measurement_coverage","gasoline_yield_average"}<={row["field"] for row in facts}


def summary(evidence):
    fields = {row["field"]:row for row in evidence["facts"]}
    if not material(evidence["facts"]):
        return ""
    gas = fields["gasoline_yield_average"]
    text = "EIA reported that U.S. refinery gasoline yields averaged "+gas["comparison"].replace("%"," percent")+" from "+gas["period"]+"."
    if "jet_fuel_yield_floor" in fields:
        jet = fields["jet_fuel_yield_floor"]
        text += " Jet-fuel yields remained "+jet["comparison"].replace("%"," percent")+" through "+jet["period"]+"."
    return text


def review(evidence):
    fields = {row["field"] for row in evidence["facts"]}
    why = ("Higher distillate and jet-fuel margins help explain the reported production shift." if "margin_incentive" in fields else
           "The dated yields describe how U.S. refiners allocated production across fuels.")
    return {"evidence":evidence,"facts":summary(evidence),"why":why,
            "watch":"Compare current fuel inventories and refinery margins with these dated product yields."}
