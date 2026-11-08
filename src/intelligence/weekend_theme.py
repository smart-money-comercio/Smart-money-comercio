"""One editorial argument chosen from concrete, original weekly disclosures."""

import re
from src.intelligence.story_analysis import checked_evidence, investor_read
from src.intelligence.daily_brief_analysis import NAMES

FRAMES={
 "business":{
  "title":"Business commitments and the route to profitable growth",
  "question":"What do this week's original disclosures change about the company's sales, costs or delivery commitments?",
  "case":"The investment question starts with what the company actually disclosed. Reported results, forward guidance, planned work and completed deliveries describe different stages of a business. Compare those stages with customer commitments, delivery costs and the timing of cash generation before changing the earnings outlook.",
  "base":"Base case: use the disclosed stage and figures as research context. Preserve the reporting period and accounting basis, and keep announced plans separate from completed business.",
  "stronger":"The case strengthens if subsequent original disclosures add paying demand, funded commitments or margins supported by delivered work. The size and timing of those commitments would help establish the business opportunity.",
  "weaker":"The case weakens if customer demand or execution falls short of disclosed plans. Higher costs, delays or weaker cash generation could reduce the benefit of sales growth; those outcomes need their own evidence."},
 "defense":{
  "title":"Defense progress and the route to funded work",
  "question":"Which defense milestones are moving toward funded delivery or a paying maintenance workload?",
  "case":"Technical progress and service designations can expand a company's opportunity, but the commercial test is the work customers actually fund. A development milestone, an existing program contract and a new order describe different kinds of evidence. The useful comparison is how each disclosure changes visibility into workload, delivery costs and eventual sales.",
  "base":"Base case: use the disclosed stages as research context while waiting for firm order values and delivery plans. The milestones support continued monitoring; they do not establish a new revenue forecast.",
  "stronger":"The case strengthens if original customer or company disclosures add funded work, production commitments or a defined service timetable. Compare the size and timing of that work with the resources needed to deliver it.",
  "weaker":"The case weakens if disclosed funding, design progress or execution falls short. Delays and higher delivery costs would matter because technical progress alone cannot establish profitable growth."},
 "ai":{
  "title":"AI investment: commitments, demand and delivery economics",
  "question":"Which disclosed AI investments have a credible path to paying demand and sustainable margins?",
  "case":"The business question extends from infrastructure spending to the demand it serves. Reported results, forward guidance, deployment plans and customer commitments carry different levels of certainty. The disclosures below provide starting points for checking whether spending is translating into sales and whether delivery costs leave room for cash generation.",
  "base":"Base case: follow the disclosed results and commitments while keeping plans separate from completed business. Compare the reporting period and accounting basis before treating two company figures as directly comparable.",
  "stronger":"The case strengthens if original disclosures show paying adoption, firm customer commitments or better margins supported by delivered work. A capacity announcement becomes more informative when its funding, utilization and delivery timetable are disclosed.",
  "weaker":"The case weakens if demand, funding or execution disappoints. Higher capital requirements or delivery costs could reduce the benefit of revenue growth; that possibility needs company evidence rather than an inference from stock prices."},
 "cyber":{
  "title":"Cybersecurity demand and the evidence of commercial adoption",
  "question":"Are new security capabilities becoming paid customer demand?",
  "case":"Security threats can create a business need, but a threat narrative does not establish a vendor's sales opportunity. The investment question is whether disclosed capabilities lead to paying adoption, customer retention and a workable cost of service. Product availability and contracted spending should remain distinct in the analysis.",
  "base":"Base case: treat the disclosed capabilities as research leads and look for adoption and contract evidence. The facts below support specific follow-up questions, rather than an assumption that the whole sector benefits equally.",
  "stronger":"The case strengthens if companies disclose paid customer expansion, durable contract commitments and margins that support the delivery model. Evidence of a customer budget matters more than the intensity of the general threat narrative.",
  "weaker":"The case weakens if disclosed adoption or customer economics disappoint. Slower commitments, implementation costs or service problems would need to be weighed against the opportunity described by the company."},
 "energy":{
  "title":"Energy conditions and the business signals behind them",
  "question":"Which current energy disclosures change the operating outlook for suppliers and customers?",
  "case":"Energy data can describe different periods and parts of the supply chain. Historical production patterns should keep their stated dates, while current operating decisions need more recent evidence. For businesses, the next links are product demand, inventories, input costs and the margins that remain after those costs.",
  "base":"Base case: retain the disclosed period and scope, then compare it with current operating evidence. A historical pattern is useful context and does not by itself establish today's supply conditions.",
  "stronger":"The case strengthens if current inventories, utilization or company results support the operating trend described in the source. Check which businesses can retain the benefit after changes in input and delivery costs.",
  "weaker":"The case weakens if newer operating data reverses the pattern or company margins fail to follow it. Price changes alone cannot identify the effect on an individual company's earnings."},
 "funding":{
  "title":"Public financing and the conditions facing businesses",
  "question":"What do the disclosed financing or policy decisions change for funding-sensitive businesses?",
  "case":"Public financing decisions can shape the conditions in which companies borrow and invest. The useful distinctions are the disclosed amounts, dates and policy scope, followed by evidence from auctions, funding markets and company plans. An equity rebound or bond-fund price move does not establish a particular yield level.",
  "base":"Base case: use the published terms as context and watch the next relevant financing evidence. Keep announced plans separate from completed demand or an asserted change in company borrowing costs.",
  "stronger":"The case strengthens if subsequent demand and company financing disclosures support easier access to funding on workable terms. Company exposure and timing still need their own evidence.",
  "weaker":"The case weakens if demand or disclosed financing terms deteriorate. Avoid assigning a uniform earnings effect across companies with different funding needs and maturity schedules."},
 "counterparty":{
  "title":"Payment channels and counterparty exposure",
  "question":"Which disclosed payment restrictions create a business exposure that can actually be traced?",
  "case":"A targeted financial action can change the risks around particular payment channels and counterparties. It does not establish that a tracked company uses those channels. The useful business follow-up is to identify disclosed exposure, available alternatives and any stated cost or operational effect.",
  "base":"Base case: retain the named targets and scope as policy context while looking for company-specific exposure. The action is evidence; a sales or earnings effect remains a separate question.",
  "stronger":"The case becomes clearer if original company disclosures identify the affected counterparties, payment routes and workable alternatives. The financial scale and timing would help distinguish a manageable change from a material business constraint.",
  "weaker":"A broad investment interpretation weakens if no relevant company exposure is disclosed or the operating effect remains unclear. A policy headline cannot substitute for that missing business connection."},
}


def group(story):
    p=checked_evidence(story);symbol=story.get("publisher_symbol","")
    if p["schema"]==13:return "counterparty"
    if p["schema"] in {10,12} or symbol in {"NOC","LMT","CACI","AVAV","KTOS","RTX","GD","HII"}:return "defense"
    if symbol=="CRWD":return "cyber"
    if symbol in {"NVDA","MSFT","AMD","TSM","AMZN","GOOG","GOOGL","AVGO","INTC","ETN","ASML","PLTR","AAPL"} and re.search(
            r"\b(?:AI|artificial intelligence|data centers?|cloud|GPU|semiconductors?)\b",p["source_text"],re.I):return "ai"
    if p["schema"]==11 or story["source"]=="EIA":return "energy"
    if story["kind"]=="company":return "business"
    return "funding"


def choose(stories):
    groups={}
    for row in stories:groups.setdefault(group(row),[]).append(row)
    if not groups:return None
    key=min(groups,key=lambda g:(-len({row.get("publisher_symbol") or row["source"] for row in groups[g]}),
                                 -sum(min(len(row["event_evidence"]["facts"]),4) for row in groups[g]),g))
    rows=sorted(groups[key],key=lambda row:(-len(row["event_evidence"]["facts"]),row["published"],row["id"]))
    selected=[];issuers=set()
    for row in rows:
        issuer=row.get("publisher_symbol") or row["source"]
        if issuer in issuers:continue
        selected.append(row["id"]);issuers.add(issuer)
        if len(selected)==3:break
    return {"id":key,**FRAMES[key],"story_ids":selected}


def name(story):
    return "Eaton" if story.get("publisher_symbol")=="ETN" else NAMES.get(story.get("publisher_symbol"),story.get("publisher_symbol") or story["source"])


def summary(story):
    p=checked_evidence(story);label=name(story)
    if p["schema"] in {12,13}:
        from src.intelligence.disclosure_details import summary as render
        return render(p,label)
    if p["schema"]==10:
        from src.intelligence.defense_program import summary as render
        return render(p,label)
    if p["schema"]==11:
        from src.intelligence.refinery_mix import summary as render
        return render(p)
    if p["schema"]==9:
        from src.intelligence.treasury_financing import summary as render
        return render(p,speech=True)
    if p["schema"]==8:
        from src.intelligence.original_disclosures import summarize
        text=summarize(story,p,label,for_speech=True)
        if text:return text
    view=investor_read(story)
    if view["facts"]:return label+": "+view["facts"]
    return label+" disclosed "+"; ".join(row["field"].replace("_"," ")+": "+row["value"] for row in p["facts"])+"."


def business(story):
    from src.intelligence.broadcast_story import company_read
    view=company_read(story) if story["kind"]=="company" else investor_read(story)
    return {"name":name(story),"why":view["why"],"watch":view["watch"]}
