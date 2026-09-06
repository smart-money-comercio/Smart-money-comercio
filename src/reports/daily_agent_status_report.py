from src.jobs.daily_agent_job import (
    format_daily_agent_result,
    load_daily_agent_status,
)


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
""".strip()

    return format_daily_agent_result(status)
