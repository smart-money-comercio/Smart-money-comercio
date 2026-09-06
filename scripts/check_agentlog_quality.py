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
        from src.reports.agentlog_report import build_agentlog_report

        report = build_agentlog_report()

    except Exception as error:
        print("Agent Log Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    register_text = Path("src/commands/register_commands.py").read_text(encoding="utf-8")
    catalog_text = Path("src/config/command_catalog.py").read_text(encoding="utf-8")

    for term in [
        "Smart Money Daily Agent Log",
        "Current Status",
        "Latest Workflow",
        "Failure Summary",
        "Recent Cron Log",
        "Troubleshooting Commands",
        "/agentstatus",
        "/rundailyagent",
        "/quality",
        "/deploycheck",
    ]:
        require(term in report, f"agent log report missing {term}", errors)

    require("agentlog_command" in register_text, "register_commands missing agentlog_command", errors)
    require('CommandHandler("agentlog"' in register_text, "register_commands missing /agentlog handler", errors)
    require("/agentlog" in catalog_text, "command catalog missing /agentlog", errors)

    print("Agent Log Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Agent Log Characters: {len(report)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
