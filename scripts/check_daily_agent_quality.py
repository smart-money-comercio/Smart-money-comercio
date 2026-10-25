import os
import sys
import argparse
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main(offline_fixture: bool = False) -> int:
    errors: list[str] = []

    try:
        from src.jobs.daily_agent_job import run_daily_agent
        from src.reports.daily_agent_status_report import build_daily_agent_status_report

        with ExitStack() as stack:
            if offline_fixture:
                from scripts.check_daily_news_brief import offline_news_fixture
                from src.jobs import daily_agent_job
                case = stack.enter_context(offline_news_fixture())
                stack.enter_context(patch.object(daily_agent_job, "STATUS_PATH", case.root / "agent.json"))
                stack.enter_context(patch.object(daily_agent_job, "build_tradeplans_step", return_value="Offline fixture trade plans; separately validated."))
                stack.enter_context(patch.object(daily_agent_job, "build_allocation_step", return_value="Offline fixture allocation; separately validated."))
                print("Validation input: isolated offline fixture; no delivery or live market report.")
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
        "Smart Money Daily News Brief",
        "Market Update",
        "Companies in Focus",
        "What's Ahead",
        "What We're Watching",
        "Research Notes",
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-fixture", action="store_true")
    raise SystemExit(main(parser.parse_args().offline_fixture))
