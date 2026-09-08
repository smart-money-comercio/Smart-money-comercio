from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STATUS_PATH = DATA_DIR / "source_refresh_status.json"

SOURCE_FILES_TO_INITIALIZE = [
    DATA_DIR / "daily_agent_cron.log",
    DATA_DIR / "daily_agent_watchdog_cron.log",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_source_refresh_status(status: dict[str, Any]) -> None:
    ensure_data_dir()
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")


def load_source_refresh_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {
            "success": False,
            "last_run": None,
            "message": "Source Refresh Engine has not run yet.",
            "steps": [],
        }

    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as error:
        return {
            "success": False,
            "last_run": None,
            "message": f"Could not read source refresh status: {type(error).__name__}: {error}",
            "steps": [],
        }


def add_step(
    steps: list[dict[str, Any]],
    name: str,
    status: str,
    detail: str,
    critical: bool = False,
) -> None:
    steps.append(
        {
            "name": name,
            "status": status,
            "detail": str(detail),
            "critical": critical,
            "time": utc_now(),
        }
    )


def run_step(
    steps: list[dict[str, Any]],
    name: str,
    func,
    critical: bool = False,
) -> Any:
    try:
        result = func()
        add_step(steps, name, "pass", result if result is not None else "Completed", critical)
        return result
    except Exception as error:
        add_step(steps, name, "fail", f"{type(error).__name__}: {error}", critical)
        return None


def call_first_available(module_name: str, function_names: list[str]) -> Any:
    module = importlib.import_module(module_name)

    for function_name in function_names:
        func = getattr(module, function_name, None)
        if callable(func):
            return func()

    raise AttributeError(f"No supported function found in {module_name}")


def get_top_symbols(limit: int = 5) -> list[str]:
    from src.scoring.scoring_engine import get_stock_scores

    raw_scores = get_stock_scores()
    items: list[tuple[str, float]] = []

    if isinstance(raw_scores, dict):
        for symbol, value in raw_scores.items():
            if isinstance(value, dict):
                score = (
                    value.get("final_score")
                    or value.get("score")
                    or value.get("smart_score")
                    or value.get("total_score")
                    or 0
                )
            else:
                score = value

            try:
                numeric_score = float(score)
            except Exception:
                numeric_score = 0

            clean_symbol = str(symbol or "").upper().replace("$", "").strip()

            if clean_symbol:
                items.append((clean_symbol, numeric_score))

    elif isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue

            symbol = str(item.get("ticker") or item.get("symbol") or "").upper().replace("$", "").strip()

            if not symbol:
                continue

            score = (
                item.get("final_score")
                or item.get("score")
                or item.get("smart_score")
                or item.get("total_score")
                or 0
            )

            try:
                numeric_score = float(score)
            except Exception:
                numeric_score = 0

            items.append((symbol, numeric_score))

    return [symbol for symbol, _score in sorted(items, key=lambda row: row[1], reverse=True)[:limit]]


def initialize_source_files() -> str:
    ensure_data_dir()

    initialized = []

    for path in SOURCE_FILES_TO_INITIALIZE:
        if not path.exists():
            path.write_text(f"Initialized by Source Refresh Engine: {utc_now()}\n", encoding="utf-8")
            initialized.append(path.name)
        elif path.stat().st_size == 0:
            path.write_text(f"Initialized by Source Refresh Engine: {utc_now()}\n", encoding="utf-8")
            initialized.append(path.name)

    if not initialized:
        return "Cron/source log files already exist."

    return "Initialized: " + ", ".join(initialized)


def refresh_news_intelligence() -> str:
    report = call_first_available(
        "src.reports.news_intelligence_report",
        [
            "build_news_intelligence_report",
            "build_news_report",
            "build_market_news_report",
        ],
    )

    return f"News Intelligence checked ({len(str(report))} chars)."


def refresh_alert_monitor() -> str:
    report = call_first_available(
        "src.reports.alert_monitor_report",
        [
            "build_alert_monitor_report",
            "build_dailyalerts_report",
            "build_alerts_report",
        ],
    )

    return f"Alert Monitor checked ({len(str(report))} chars)."


def refresh_context_providers() -> str:
    import src.intelligence.intelligence_context_providers  # noqa: F401
    from src.intelligence.intelligence_context_registry import collect_intelligence_context

    blocks = collect_intelligence_context()
    features = [str(block.feature or "").strip() for block in blocks if str(block.feature or "").strip()]

    if not features:
        return "Context provider registry loaded, but no providers returned blocks."

    return "Context providers loaded: " + ", ".join(features)


def refresh_stockanalysis_top_names(force_refresh: bool = True, limit: int = 3) -> str:
    from src.intelligence.stockanalysis_source import fetch_stockanalysis_data

    symbols = get_top_symbols(limit=limit)

    if not symbols:
        return "No top-ranked symbols available for StockAnalysis refresh."

    refreshed = []
    failed = []

    for symbol in symbols:
        try:
            try:
                fetch_stockanalysis_data(symbol, force_refresh=force_refresh)
            except TypeError:
                try:
                    fetch_stockanalysis_data(symbol, refresh=force_refresh)
                except TypeError:
                    fetch_stockanalysis_data(symbol)

            refreshed.append(symbol)
        except Exception as error:
            failed.append(f"{symbol}: {type(error).__name__}")

    if refreshed and failed:
        return "StockAnalysis refreshed for " + ", ".join(refreshed) + "; failed: " + ", ".join(failed)

    if refreshed:
        return "StockAnalysis refreshed for: " + ", ".join(refreshed)

    return "StockAnalysis refresh failed for: " + ", ".join(failed)


def build_source_health_after_refresh() -> str:
    from src.reports.sourcehealth_report import build_sourcehealth_report

    report = build_sourcehealth_report()

    if not report:
        raise RuntimeError("Source health report returned empty output.")

    status_line = "UNKNOWN"

    for line in report.splitlines():
        if line.startswith("Status:"):
            status_line = line.replace("Status:", "").strip()
            break

    return f"Source health rebuilt. Status: {status_line}. Report length: {len(report)} chars."


def run_source_refresh(dry_run: bool = False) -> dict[str, Any]:
    started_at = utc_now()
    steps: list[dict[str, Any]] = []

    os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0" if dry_run else "1")

    run_step(steps, "Initialize Source Files", initialize_source_files, critical=True)
    run_step(steps, "News Intelligence", refresh_news_intelligence)
    run_step(steps, "Alert Monitor", refresh_alert_monitor)
    run_step(steps, "Context Providers", refresh_context_providers, critical=True)

    if dry_run:
        add_step(steps, "StockAnalysis Refresh", "skip", "Skipped during dry run.")
    else:
        run_step(steps, "StockAnalysis Refresh", refresh_stockanalysis_top_names)

    run_step(steps, "Source Health Recheck", build_source_health_after_refresh, critical=True)

    critical_failures = [
        step for step in steps
        if step.get("critical") and step.get("status") == "fail"
    ]

    soft_failures = [
        step for step in steps
        if not step.get("critical") and step.get("status") == "fail"
    ]

    success = not critical_failures
    overall_status = "PASS" if success and not soft_failures else "WARNING" if success else "FAIL"

    status = {
        "success": success,
        "overall_status": overall_status,
        "last_run": started_at,
        "completed_at": utc_now(),
        "dry_run": dry_run,
        "message": (
            "Source refresh completed successfully."
            if overall_status == "PASS"
            else "Source refresh completed with warnings."
            if overall_status == "WARNING"
            else "Source refresh failed."
        ),
        "steps": steps,
    }

    save_source_refresh_status(status)

    return status


def format_source_refresh_result(status: dict[str, Any]) -> str:
    lines = [
        "Source Refresh Engine",
        f"Status: {status.get('overall_status') or ('PASS' if status.get('success') else 'FAIL')}",
        f"Last Run: {status.get('last_run') or 'Not available'}",
        f"Completed At: {status.get('completed_at') or 'Not available'}",
        f"Dry Run: {status.get('dry_run')}",
        f"Message: {status.get('message') or 'No message'}",
        "",
        "Refresh Steps",
    ]

    for step in status.get("steps", []):
        marker = {
            "pass": "PASS",
            "fail": "FAIL",
            "skip": "SKIP",
        }.get(str(step.get("status") or "").lower(), str(step.get("status") or "").upper())

        lines.append(f"- {marker}: {step.get('name')} - {step.get('detail')}")

    lines.extend(
        [
            "",
            "Next Commands",
            "/sourcehealth",
            "/agentlog",
            "/watchdog",
            "/agentstatus",
            "/quality",
            "/deploycheck",
            "",
            "Research only. Not financial advice.",
        ]
    )

    return "\n".join(lines)
