import ast
import os
from pathlib import Path
from typing import Any

from src.config import command_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTER_COMMANDS_FILE = PROJECT_ROOT / "src" / "commands" / "register_commands.py"

STRICT_COMMAND_AUDIT = os.getenv("STRICT_COMMAND_AUDIT", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


COMMAND_GROUP_NAMES = [
    "CORE_COMMANDS",
    "DAILY_REPORT_COMMANDS",
    "STOCK_RESEARCH_COMMANDS",
    "THEME_COMMANDS",
    "MARKET_CONTEXT_COMMANDS",
    "SMART_MONEY_COMMANDS",
    "ADMIN_COMMANDS",
]


INTENTIONAL_INTERNAL_COMMANDS = {
    "start",
    "help",
    "commands",
    "admin",
}


def normalize_command(value: Any) -> str:
    text = str(value or "").strip()

    if not text:
        return ""

    # Handles catalog entries like "/stock SYMBOL".
    text = text.split()[0].strip()

    if text.startswith("/"):
        text = text[1:]

    return text.strip().lower()


def get_catalog_commands() -> set[str]:
    commands = set()

    for group_name in COMMAND_GROUP_NAMES:
        group = getattr(command_catalog, group_name, [])

        for item in group:
            if not isinstance(item, (list, tuple)) or not item:
                continue

            command = normalize_command(item[0])

            if command:
                commands.add(command)

    for item in getattr(command_catalog, "ALIASES", []):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue

        alias = normalize_command(item[0])
        target = normalize_command(item[1])

        if alias:
            commands.add(alias)

        if target:
            commands.add(target)

    return commands


def get_command_handler_name(node: ast.Call) -> str:
    function = node.func

    if isinstance(function, ast.Name):
        return function.id

    if isinstance(function, ast.Attribute):
        return function.attr

    return ""


def extract_registered_commands_from_source(path: Path = REGISTER_COMMANDS_FILE) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    commands = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if get_command_handler_name(node) != "CommandHandler":
            continue

        if not node.args:
            continue

        first_arg = node.args[0]

        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            command = normalize_command(first_arg.value)

            if command:
                commands.append(command)

    return commands


def count_items(items: list[str]) -> dict[str, int]:
    counts = {}

    for item in items:
        counts[item] = counts.get(item, 0) + 1

    return counts


def audit_command_catalog() -> dict:
    catalog_commands = get_catalog_commands()
    registered_commands_list = extract_registered_commands_from_source()
    registered_commands = set(registered_commands_list)
    registered_counts = count_items(registered_commands_list)

    missing_from_registry = sorted(catalog_commands - registered_commands)

    duplicate_registered = sorted(
        command
        for command, count in registered_counts.items()
        if count > 1
    )

    uncataloged_registered = sorted(
        command
        for command in registered_commands - catalog_commands
        if command not in INTENTIONAL_INTERNAL_COMMANDS
    )

    passes = (
        not missing_from_registry
        and not duplicate_registered
        and (not STRICT_COMMAND_AUDIT or not uncataloged_registered)
    )

    return {
        "passes": passes,
        "strict": STRICT_COMMAND_AUDIT,
        "catalog_count": len(catalog_commands),
        "registered_count": len(registered_commands),
        "missing_from_registry": missing_from_registry,
        "duplicate_registered": duplicate_registered,
        "uncataloged_registered": uncataloged_registered,
        "catalog_commands": sorted(catalog_commands),
        "registered_commands": sorted(registered_commands),
    }


def format_items(items: list[str]) -> str:
    if not items:
        return "None"

    return ", ".join(f"/{item}" for item in items)


def format_command_audit_report(result: dict) -> str:
    status = "PASS" if result.get("passes") else "FAIL"

    return f"""
Command Catalog Audit
Status: {status}
Strict Mode: {result.get("strict")}

Catalog Commands: {result.get("catalog_count")}
Registered Commands: {result.get("registered_count")}

Missing From Registry: {format_items(result.get("missing_from_registry") or [])}
Duplicate Registered: {format_items(result.get("duplicate_registered") or [])}
Registered But Not Cataloged: {format_items(result.get("uncataloged_registered") or [])}
""".strip()


def main() -> int:
    result = audit_command_catalog()
    print(format_command_audit_report(result))

    return 0 if result.get("passes") else 1


if __name__ == "__main__":
    raise SystemExit(main())