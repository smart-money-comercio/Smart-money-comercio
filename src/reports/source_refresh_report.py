from src.jobs.source_refresh_job import (
    format_source_refresh_result,
    load_source_refresh_status,
)


def build_source_refresh_status_report() -> str:
    status = load_source_refresh_status()

    if not status.get("last_run"):
        return """
Source Refresh Engine
Status: NOT RUN YET

The Source Refresh Engine has not completed a saved run yet.

Use:
/refreshsources

Then check:
/sourcehealth
/watchdog
/quality
/deploycheck
""".strip()

    return format_source_refresh_result(status)
