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
        from src.reports.watchdog_report import build_watchdog_payload, build_watchdog_report

        payload = build_watchdog_payload()
        report = build_watchdog_report()

    except Exception as error:
        print("Watchdog Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    register_text = Path("src/commands/register_commands.py").read_text(encoding="utf-8")
    catalog_text = Path("src/config/command_catalog.py").read_text(encoding="utf-8")
    runner_text = Path("scripts/run_watchdog.py").read_text(encoding="utf-8")

    for term in [
        "Daily Agent Watchdog",
        "Watchdog Status",
        "Schedule Check",
        "Daily Agent Health",
        "Workflow Evidence",
        "Telegram Send Evidence",
        "Recent Cron Error Evidence",
        "Next Commands",
        "/agentlog",
        "/agentstatus",
        "/rundailyagent",
        "/quality",
        "/deploycheck",
    ]:
        require(term in report, f"watchdog report missing {term}", errors)

    require(payload.get("watchdog_status") in {"PASS", "WARNING", "FAIL", "WAITING", "OFF"}, "invalid watchdog status", errors)
    require("watchdog_command" in register_text, "register_commands missing watchdog_command", errors)
    require('CommandHandler("watchdog"' in register_text, "register_commands missing /watchdog handler", errors)
    require("/watchdog" in catalog_text, "command catalog missing /watchdog", errors)
    require("build_watchdog_report" in runner_text, "run_watchdog.py missing report builder", errors)

    print("Watchdog Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Watchdog Report Characters: {len(report)}")
    print(f"Watchdog Status: {payload.get('watchdog_status')}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
