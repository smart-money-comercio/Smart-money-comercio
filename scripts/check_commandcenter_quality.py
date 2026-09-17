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
        from src.reports.commandcenter_report import build_commandcenter_report

        report = build_commandcenter_report()

    except Exception as error:
        print("Command Center Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    register_text = Path(
        "src/commands/register_commands.py"
    ).read_text(encoding="utf-8")

    catalog_text = Path(
        "src/config/command_catalog.py"
    ).read_text(encoding="utf-8")

    required_sections = [
        "Smart Money AI Command Center",
        "System Status",
        "Daily Agent",
        "Source Health",
        "Source Refresh Engine",
        "Daily Agent Watchdog",
        "Decision Tools",
        "Operations",
        "System",
    ]

    for section in required_sections:
        require(
            section in report,
            f"Command Center missing section {section}",
            errors,
        )

    required_commands = [
        "/brief",
        "/allocation",
        "/tradeplans",
        "/rundailyagent",
        "/refreshsources",
        "/sourcehealth",
        "/watchdog",
        "/agentlog",
        "/agentstatus",
        "/quality",
        "/deploycheck",
        "/commandcenter",
    ]

    for command in required_commands:
        require(
            command in report,
            f"Command Center missing {command}",
            errors,
        )

    require(
        "commandcenter_command" in register_text,
        "register_commands missing commandcenter_command",
        errors,
    )

    require(
        'CommandHandler("commandcenter"' in register_text,
        "register_commands missing /commandcenter handler",
        errors,
    )

    require(
        "/commandcenter" in catalog_text,
        "command catalog missing /commandcenter",
        errors,
    )

    print("Command Center Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Command Center Characters: {len(report)}")

    if errors:
        print("")
        print("Errors:")

        for error in errors:
            print(f"- {error}")

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
