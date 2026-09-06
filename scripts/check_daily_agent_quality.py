import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        from src.jobs.daily_agent_job import run_daily_agent
        from src.reports.daily_agent_status_report import build_daily_agent_status_report

        result = run_daily_agent(dry_run=True)
        status_report = build_daily_agent_status_report()
        daily_report = result.get("report", "")

    except Exception as error:
        print("Daily Agent Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    register_text = Path("src/commands/register_commands.py").read_text(encoding="utf-8")
    catalog_text = Path("src/config/command_catalog.py").read_text(encoding="utf-8")

    require(result.get("success") is True, "daily agent dry run did not pass", errors)
    require("Smart Money Daily Agent" in status_report, "status report missing title", errors)
    require("Workflow" in status_report, "status report missing workflow", errors)
    require("Daily Report Build" in status_report, "status report missing Daily Report Build step", errors)
    require("Quality Review" in status_report, "status report missing Quality Review step", errors)

    for term in [
        "Executive Summary",
        "Smart Money Summary",
        "Trade Plan Snapshot",
        "Portfolio Allocation Snapshot",
        "Intelligence Used Today",
        "Research only. Not financial advice.",
    ]:
        require(term in daily_report, f"daily report missing {term}", errors)

    require("agentstatus_command" in register_text, "register_commands missing agentstatus_command", errors)
    require("rundailyagent_command" in register_text, "register_commands missing rundailyagent_command", errors)
    require("/agentstatus" in catalog_text, "command catalog missing /agentstatus", errors)
    require("/rundailyagent" in catalog_text, "command catalog missing /rundailyagent", errors)

    print("Daily Agent Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Status Report Characters: {len(status_report)}")
    print(f"Daily Report Characters: {len(daily_report)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
