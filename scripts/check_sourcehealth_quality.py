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
        from src.reports.sourcehealth_report import build_sourcehealth_report

        report = build_sourcehealth_report()

    except Exception as error:
        print("Source Health Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    register_text = Path("src/commands/register_commands.py").read_text(encoding="utf-8")
    catalog_text = Path("src/config/command_catalog.py").read_text(encoding="utf-8")

    for term in [
        "Data Source Health Dashboard",
        "Overall Health",
        "Daily Agent Status",
        "Core Source Files",
        "StockAnalysis Cache Evidence",
        "Context Provider Registration",
        "Module Import Health",
        "Telegram Configuration",
        "Next Commands",
        "/sourcehealth",
        "/agentlog",
        "/watchdog",
        "/agentstatus",
        "/quality",
        "/deploycheck",
    ]:
        require(term in report, f"sourcehealth report missing {term}", errors)

    require("sourcehealth_command" in register_text, "register_commands missing sourcehealth_command", errors)
    require('CommandHandler("sourcehealth"' in register_text, "register_commands missing /sourcehealth handler", errors)
    require("/sourcehealth" in catalog_text, "command catalog missing /sourcehealth", errors)

    print("Source Health Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Source Health Characters: {len(report)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
