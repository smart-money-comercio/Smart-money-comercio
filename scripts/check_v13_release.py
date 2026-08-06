import importlib
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")
os.environ.setdefault("STRICT_COMMAND_AUDIT", "1")


REQUIRED_REPORT_BUILDERS = [
    ("src.reports.smartmoney_command_center_report", "build_smartmoney_command_center_report"),
    ("src.reports.conviction_command_center_report", "build_conviction_command_center_report"),
    ("src.reports.global_intelligence_report", "build_global_intelligence_report"),
    ("src.reports.portfolio_intelligence_report", "build_portfolio_intelligence_report"),
    ("src.reports.defense_intelligence_report", "build_defense_intelligence_report"),
    ("src.reports.stock_intelligence_report", "build_stock_intelligence_report"),
    ("src.reports.scorecard_intelligence_report", "build_scorecard_intelligence_report"),
    ("src.reports.risk_intelligence_report", "build_risk_intelligence_report"),
    ("src.reports.volume_intelligence_report", "build_volume_intelligence_report"),
    ("src.reports.earnings_intelligence_report", "build_earnings_intelligence_report"),
    ("src.reports.analyst_intelligence_report", "build_analyst_intelligence_report"),
    ("src.reports.filing_intelligence_report", "build_filing_intelligence_report"),
    ("src.reports.top10_report", "build_top10_report"),
    ("src.reports.daily_report", "build_daily_report"),
]


REQUIRED_COMMANDS = [
    "/smartmoney",
    "/conviction",
    "/global",
    "/portfolio",
    "/defense",
    "/snapshot",
    "/top10",
    "/brief",
    "/report",
    "/stock",
    "/scorecard",
    "/risk",
    "/volume",
    "/earnings",
    "/analyst",
    "/sec",
    "/filing",
    "/quality",
    "/deploycheck",
    "/version",
    "/versionnotes",
]


def normalize_command_value(value: Any) -> set[str]:
    commands: set[str] = set()

    if isinstance(value, str):
        if value.startswith("/"):
            commands.add(value.split()[0].strip())
        return commands

    if isinstance(value, dict):
        for key in ["command", "name", "primary", "alias"]:
            item = value.get(key)
            if isinstance(item, str) and item.startswith("/"):
                commands.add(item.split()[0].strip())

        for item in value.values():
            commands.update(normalize_command_value(item))

        return commands

    if isinstance(value, (list, tuple, set)):
        for item in value:
            commands.update(normalize_command_value(item))

        return commands

    return commands


def collect_catalog_commands(catalog: Any) -> set[str]:
    commands: set[str] = set()

    # Preferred helper if available.
    if hasattr(catalog, "get_primary_commands"):
        try:
            commands.update(normalize_command_value(catalog.get_primary_commands()))
        except Exception:
            pass

    # Pull all command constants such as CORE_COMMANDS, ADMIN_COMMANDS, ALIASES, etc.
    for name in dir(catalog):
        if name.startswith("_"):
            continue

        if not (
            name.endswith("_COMMANDS")
            or name in {"ALIASES", "COMMANDS", "COMMAND_CATALOG"}
        ):
            continue

        try:
            value = getattr(catalog, name)
        except Exception:
            continue

        commands.update(normalize_command_value(value))

    return commands


def check_version_info(errors: list[str]) -> None:
    try:
        version_info = importlib.import_module("src.config.version_info")
    except Exception as error:
        errors.append(f"version_info import failed: {type(error).__name__}: {error}")
        return

    app_version = getattr(version_info, "APP_VERSION", "")
    release_status = getattr(version_info, "RELEASE_STATUS", "")
    release_name = getattr(version_info, "RELEASE_NAME", "")

    if app_version != "v1.3":
        errors.append(f"APP_VERSION expected v1.3, found {app_version!r}")

    if release_status != "Stable":
        errors.append(f"RELEASE_STATUS expected Stable, found {release_status!r}")

    if "Intelligence" not in str(release_name):
        errors.append(
            f"RELEASE_NAME should describe intelligence release, found {release_name!r}"
        )

    notes = "\n".join(getattr(version_info, "RELEASE_NOTES", []))
    stack = "\n".join(getattr(version_info, "V13_COMMAND_STACK", []))

    for command in ["/smartmoney", "/conviction", "/global", "/portfolio", "/defense"]:
        if command not in notes and command not in stack:
            errors.append(f"version notes missing {command}")


def check_report_builders(errors: list[str]) -> None:
    for module_name, function_name in REQUIRED_REPORT_BUILDERS:
        try:
            module = importlib.import_module(module_name)
        except Exception as error:
            errors.append(
                f"{module_name} import failed: {type(error).__name__}: {error}"
            )
            continue

        if not hasattr(module, function_name):
            errors.append(f"{module_name} missing {function_name}")


def check_command_catalog(errors: list[str]) -> None:
    try:
        catalog = importlib.import_module("src.config.command_catalog")
    except Exception as error:
        errors.append(f"command_catalog import failed: {type(error).__name__}: {error}")
        return

    catalog_commands = collect_catalog_commands(catalog)

    for command in REQUIRED_COMMANDS:
        if command not in catalog_commands:
            errors.append(f"command catalog missing {command}")


def main() -> int:
    errors: list[str] = []

    check_version_info(errors)
    check_report_builders(errors)
    check_command_catalog(errors)

    print("v1.3 Release Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Required Commands: {len(REQUIRED_COMMANDS)}")
    print(f"Report Builders: {len(REQUIRED_REPORT_BUILDERS)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")

        return 1

    print("")
    print("Release Status: Stable")
    print("v1.3 intelligence stack is production-ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())