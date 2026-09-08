from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"

KNOWN_FILES = {
    "Daily Agent Status": DATA_DIR / "daily_agent_status.json",
    "Daily Agent Cron Log": DATA_DIR / "daily_agent_cron.log",
    "Watchdog Cron Log": DATA_DIR / "daily_agent_watchdog_cron.log",
    "Alert Monitor Memory": DATA_DIR / "alert_monitor_memory.json",
}

EXPECTED_CONTEXT_PROVIDERS = [
    "Alert Monitor",
    "News Intelligence",
    "StockAnalysis Cache",
    "Alert Settings",
]

EXPECTED_MODULES = {
    "Daily Report": "src.reports.daily_report",
    "Trade Plans": "src.reports.tradeplans_report",
    "Allocation": "src.reports.allocation_report",
    "Daily Agent": "src.jobs.daily_agent_job",
    "Agent Log": "src.reports.agentlog_report",
    "Watchdog": "src.reports.watchdog_report",
    "StockAnalysis Source": "src.intelligence.stockanalysis_source",
    "News Intelligence": "src.reports.news_intelligence_report",
    "Alert Monitor": "src.reports.alert_monitor_report",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_text() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def compact(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\r", "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def load_env_map() -> dict[str, str]:
    values = dict(os.environ)

    if not ENV_PATH.exists():
        return values

    try:
        text = ENV_PATH.read_text(encoding="utf-8-sig")
    except Exception:
        return values

    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        if stripped.startswith("export "):
            stripped = stripped.replace("export ", "", 1).strip()

        key, value = stripped.split("=", 1)
        values.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    return values


def file_age_minutes(path: Path) -> float | None:
    if not path.exists():
        return None

    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return max(0.0, (utc_now() - modified).total_seconds() / 60)


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def age_label(minutes: float | None) -> str:
    if minutes is None:
        return "missing"
    if minutes < 60:
        return f"{minutes:.0f} min ago"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} hours ago"
    return f"{hours / 24:.1f} days ago"


def health_label_for_file(path: Path, max_age_hours: int | None = None) -> str:
    if not path.exists():
        return "MISSING"

    if file_size(path) <= 0:
        return "EMPTY"

    if max_age_hours is not None:
        minutes = file_age_minutes(path)
        if minutes is not None and minutes > max_age_hours * 60:
            return "STALE"

    return "OK"


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return {"_error": f"{type(error).__name__}: {error}"}


def source_file_lines() -> list[str]:
    max_age = {
        "Daily Agent Status": 96,
        "Daily Agent Cron Log": 168,
        "Watchdog Cron Log": 168,
        "Alert Monitor Memory": 1080,
    }

    lines = []

    for label, path in KNOWN_FILES.items():
        status = health_label_for_file(path, max_age_hours=max_age.get(label))
        lines.append(
            f"- {label}: {status} | size {file_size(path)} bytes | modified {age_label(file_age_minutes(path))}"
        )

    return lines


def find_stockanalysis_cache_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []

    files: list[Path] = []

    for pattern in ["*stockanalysis*", "*stock_analysis*", "*fundamental*", "*analyst*"]:
        files.extend(path for path in DATA_DIR.rglob(pattern) if path.is_file())

    unique = sorted(set(files), key=lambda item: item.stat().st_mtime, reverse=True)
    return unique


def stockanalysis_lines(limit: int = 6) -> list[str]:
    files = find_stockanalysis_cache_files()

    if not files:
        return ["- StockAnalysis Cache: NOT FOUND | no cache files detected in data"]

    lines = []

    for path in files[:limit]:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        lines.append(
            f"- {rel}: OK | size {file_size(path)} bytes | modified {age_label(file_age_minutes(path))}"
        )

    return lines


def context_provider_lines() -> list[str]:
    try:
        import src.intelligence.intelligence_context_providers  # noqa: F401
        from src.intelligence.intelligence_context_registry import collect_intelligence_context

        blocks = collect_intelligence_context()
        loaded = {str(block.feature or "").strip() for block in blocks}
    except Exception as error:
        return [f"- Context Providers: FAIL | {type(error).__name__}: {compact(error, 100)}"]

    return [
        f"- {provider}: {'OK' if provider in loaded else 'NOT LOADED'}"
        for provider in EXPECTED_CONTEXT_PROVIDERS
    ]


def module_lines() -> list[str]:
    lines = []

    for label, module_name in EXPECTED_MODULES.items():
        try:
            importlib.import_module(module_name)
            lines.append(f"- {label}: OK | OK")
        except Exception as error:
            lines.append(f"- {label}: FAIL | {compact(type(error).__name__ + ': ' + str(error), 120)}")

    return lines


def telegram_env_lines() -> list[str]:
    env = load_env_map()

    token = env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_TOKEN") or env.get("BOT_TOKEN")
    destination = env.get("TELEGRAM_CHANNEL_ID") or env.get("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_COMMAND_CHAT_ID")

    return [
        f"- Telegram bot token: {'OK' if token else 'MISSING'}",
        f"- Telegram destination: {'OK' if destination else 'MISSING'}",
        f"- TELEGRAM_BOT_TOKEN: {'OK' if env.get('TELEGRAM_BOT_TOKEN') else 'MISSING'}",
        f"- TELEGRAM_CHANNEL_ID: {'OK' if env.get('TELEGRAM_CHANNEL_ID') else 'MISSING'}",
        f"- TELEGRAM_CHAT_ID: {'OK' if env.get('TELEGRAM_CHAT_ID') else 'MISSING'}",
        f"- TELEGRAM_COMMAND_CHAT_ID: {'OK' if env.get('TELEGRAM_COMMAND_CHAT_ID') else 'MISSING'}",
    ]


def daily_agent_status_lines() -> list[str]:
    status = read_json_file(KNOWN_FILES["Daily Agent Status"])

    if not status:
        return ["- Daily Agent Status: NOT FOUND"]

    if "_error" in status:
        return [f"- Daily Agent Status: FAIL | {status['_error']}"]

    success = status.get("success")

    return [
        f"- Success: {'YES' if success is True else 'NO' if success is False else 'UNKNOWN'}",
        f"- Last Run: {status.get('last_run') or 'Not available'}",
        f"- Completed At: {status.get('completed_at') or 'Not available'}",
        f"- Report Characters: {status.get('report_characters', 0)}",
        f"- Message: {compact(status.get('message') or 'No message', 160)}",
    ]


def compute_overall_health() -> tuple[str, list[str]]:
    warnings = []
    failures = []

    daily_status = read_json_file(KNOWN_FILES["Daily Agent Status"])

    if not daily_status:
        failures.append("daily agent status file missing")
    elif daily_status.get("success") is not True:
        warnings.append("latest daily agent status is not PASS")

    for label, path in KNOWN_FILES.items():
        status = health_label_for_file(path, max_age_hours=168 if "Cron" in label else 1080)

        if status == "MISSING":
            warnings.append(f"{label} missing")
        elif status in {"EMPTY", "STALE"}:
            warnings.append(f"{label} is {status.lower()}")

    if any("FAIL" in line for line in module_lines()):
        failures.append("one or more source modules failed import")

    if any("FAIL" in line for line in context_provider_lines()):
        failures.append("context provider collection failed")

    env = load_env_map()
    token = env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_TOKEN") or env.get("BOT_TOKEN")
    destination = env.get("TELEGRAM_CHANNEL_ID") or env.get("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_COMMAND_CHAT_ID")

    if not token or not destination:
        warnings.append("Telegram configuration is incomplete or not readable")

    if failures:
        return "FAIL", failures + warnings

    if warnings:
        return "WARNING", warnings

    return "PASS", ["All required source-health checks are available."]


def build_sourcehealth_report() -> str:
    overall, notes = compute_overall_health()

    return f"""
Data Source Health Dashboard

Overall Health
Status: {overall}
Notes:
{chr(10).join(f"- {compact(note, 180)}" for note in notes)}

Daily Agent Status
{chr(10).join(daily_agent_status_lines())}

Core Source Files
{chr(10).join(source_file_lines())}

StockAnalysis Cache Evidence
{chr(10).join(stockanalysis_lines())}

Context Provider Registration
{chr(10).join(context_provider_lines())}

Module Import Health
{chr(10).join(module_lines())}

Telegram Configuration
{chr(10).join(telegram_env_lines())}

Next Commands
/sourcehealth
/agentlog
/watchdog
/agentstatus
/rundailyagent
/quality
/deploycheck

Generated: {utc_now_text()}
""".strip()
