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
        from src.jobs.source_refresh_job import run_source_refresh, format_source_refresh_result
        from src.reports.source_refresh_report import build_source_refresh_status_report

        result = run_source_refresh(dry_run=True)
        output = format_source_refresh_result(result)
        status_report = build_source_refresh_status_report()

    except Exception as error:
        print("Source Refresh Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    register_text = Path("src/commands/register_commands.py").read_text(encoding="utf-8")
    catalog_text = Path("src/config/command_catalog.py").read_text(encoding="utf-8")
    runner_text = Path("scripts/run_refresh_sources.py").read_text(encoding="utf-8")

    for term in [
        "Source Refresh Engine",
        "Refresh Steps",
        "Initialize Source Files",
        "News Intelligence",
        "Alert Monitor",
        "Context Providers",
        "StockAnalysis Refresh",
        "Source Health Recheck",
        "Next Commands",
        "/sourcehealth",
        "/watchdog",
        "/quality",
        "/deploycheck",
    ]:
        require(term in output, f"refresh output missing {term}", errors)

    require("Source Refresh Engine" in status_report, "status report missing title", errors)
    require(result.get("success") is True, "dry run source refresh did not pass", errors)
    require("refreshsources_command" in register_text, "register_commands missing refreshsources_command", errors)
    require('CommandHandler("refreshsources"' in register_text, "register_commands missing /refreshsources handler", errors)
    require("/refreshsources" in catalog_text, "command catalog missing /refreshsources", errors)
    require("run_source_refresh" in runner_text, "run_refresh_sources.py missing run_source_refresh", errors)

    print("Source Refresh Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Output Characters: {len(output)}")
    print(f"Status Report Characters: {len(status_report)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
