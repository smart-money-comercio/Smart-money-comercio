from src.jobs.daily_agent_job import (
    format_daily_agent_result,
    load_daily_agent_status,
)
from src.utils.daily_agent_delivery import status_suffix


def build_daily_agent_status_report() -> str:
    status = load_daily_agent_status()

    if not status.get("last_run"):
        return """
Smart Money Daily Agent
Status: NOT RUN YET

The daily agent has not completed a saved run yet.

Use:
/rundailyagent

Then check:
/agentstatus
/quality
/deploycheck
""".strip() + status_suffix(status)

    return format_daily_agent_result(status) + status_suffix(status)
