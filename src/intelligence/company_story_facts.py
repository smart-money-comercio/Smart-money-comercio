"""Admission and follow-up checks for concrete company disclosure facts."""

from src.intelligence.story_analysis import checked_evidence


POLICY_VERSION = 1
BODY_REQUIRED = "Original release body required for company facts"
FACT_REQUIRED = "Original company disclosure yielded no concrete business fact"
DEAL_VALUES = ("transaction_value", "enterprise_value", "equity_value")
FINANCIAL_RESULTS = ("reported_revenue", "reported_sales", "reported_net_sales", "reported_operating_margin", "reported_eps")
GENERAL_FIELDS = (
    *DEAL_VALUES, "forecast_revenue", *FINANCIAL_RESULTS, "contract_value", "obligated_amount", "contract_ceiling",
    "restructuring_charge", "restructuring_cost_estimate", "annual_savings_target", "deployment_example",
)
SPECIALIZED_FIELDS = {
    10: ("development_test",),
    12: ("maintenance_designation",),
    14: ("customer_purchases", "system_shipments", "delivery_milestone"),
    15: ("order_value",),
    16: ("optimization_target",),
    18: ("dividend_per_share",),
}


def required_field(story, now):
    """Return the narrated fact that enables publication of this company story."""
    from src.intelligence.news_editor import MAX_CACHE_AGE, dated, title_key

    proof = checked_evidence(story)
    if proof["scope"] != "original release excerpt":
        raise ValueError(BODY_REQUIRED)
    observed, published = dated(proof["observed_at"]), dated(proof["published"])
    if not -60 <= (now - observed).total_seconds() <= MAX_CACHE_AGE or (published - observed).total_seconds() > 60:
        raise ValueError("Original article observation is stale, future-dated or predates publication")
    headline = title_key(story["title"])
    facts = {row["field"]: row for row in proof["facts"]}
    for field in SPECIALIZED_FIELDS.get(proof["schema"], GENERAL_FIELDS):
        row = facts.get(field)
        if row and row["value"] and title_key(row["evidence"]) not in {"", headline}:
            return field
    raise ValueError(FACT_REQUIRED)


def validate_edition(plan):
    """Recheck admissions from frozen source text and the edition's clock."""
    if "company_fact_policy" not in plan:
        return
    if type(plan["company_fact_policy"]) is not int or plan["company_fact_policy"] != POLICY_VERSION:
        raise ValueError("Unknown company fact policy")
    from src.intelligence.news_editor import dated, primary_source, selected_stories

    now = dated(plan["generated_at"])
    for story in selected_stories(plan):
        if story["kind"] == "company" and (story.get("source_check") != "pass" or not primary_source(story)
                or story.get("company_fact") != required_field(story, now)):
            raise ValueError("Selected company story lost its admitted business fact")


def follow_up(story):
    """Give the reader a test tied to the reported amount or operating measure."""
    field = story.get("company_fact")
    if field in DEAL_VALUES:
        proof = story["event_evidence"]
        amount = next(row["value"] for row in proof["facts"] if row["field"] == field)
        if proof["event"] == "divestiture":
            return f"Use the stated deal value of {amount} as the benchmark for reported net proceeds and transition costs."
        if proof["stage"] == "completed":
            return f"The stated deal value was {amount}. Watch how much cash the acquired business generates after integration costs."
        if proof["stage"] == "terminated":
            return "Check the termination payment and what management plans to do with the capital set aside for the deal."
        return f"The stated deal value was {amount}. Watch how much would be financed with debt and when required approvals are due."
    if field == "forecast_revenue":
        return "Compare the next reported revenue with this forecast and check whether gross margins moved in the same direction."
    if field in FINANCIAL_RESULTS:
        return "Use this result as the baseline for the next quarter. Check whether growth also improves margins and operating cash flow."
    if field in {"contract_value", "contract_ceiling", "obligated_amount"}:
        return "Compare the disclosed amount with funded work and the start of deliveries. That will help establish when sales can follow."
    if field in {"restructuring_charge", "restructuring_cost_estimate", "annual_savings_target"}:
        return "Compare actual savings with restructuring costs in the next results to see when the changes start improving cash flow."
    return ""
