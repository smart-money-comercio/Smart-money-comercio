from __future__ import annotations

import importlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_PATH = Path("data/daily_agent_status.json")

REQUIRED_DAILY_REPORT_TERMS = [
    "Executive Summary",
    "Intelligence Used Today",
    "Smart Money Summary",
    "Trade Plan Snapshot",
    "Portfolio Allocation Snapshot",
    "Action Checklist",
    "Next Commands",
    "Research only. Not financial advice.",
]


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_data_dir() -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)


def save_daily_agent_status(status: dict[str, Any]) -> None:
    ensure_data_dir()
    safe_status = dict(status)
    safe_status.pop("report", None)
    STATUS_PATH.write_text(json.dumps(safe_status, indent=2), encoding="utf-8")


def load_daily_agent_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {
            "success": False,
            "last_run": None,
            "message": "Daily agent has not run yet.",
            "steps": [],
        }

    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as error:
        return {
            "success": False,
            "last_run": None,
            "message": f"Could not read daily agent status: {type(error).__name__}: {error}",
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
            "detail": detail,
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
        detail = str(result) if result is not None else "Completed"
        add_step(steps, name, "pass", detail, critical=critical)
        return result
    except Exception as error:
        add_step(
            steps,
            name,
            "fail",
            f"{type(error).__name__}: {error}",
            critical=critical,
        )
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

    if isinstance(raw_scores, dict):
        items = []
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

            items.append((str(symbol).upper(), numeric_score))

        return [symbol for symbol, _score in sorted(items, key=lambda item: item[1], reverse=True)[:limit]]

    if isinstance(raw_scores, list):
        items = []
        for item in raw_scores:
            if not isinstance(item, dict):
                continue

            symbol = str(item.get("ticker") or item.get("symbol") or "").upper().strip()
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

        return [symbol for symbol, _score in sorted(items, key=lambda item: item[1], reverse=True)[:limit]]

    return []


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


def refresh_stockanalysis_top_names() -> str:
    from src.intelligence.stockanalysis_source import fetch_stockanalysis_data

    symbols = get_top_symbols(limit=3)

    if not symbols:
        return "No top symbols available for StockAnalysis refresh."

    refreshed = []

    for symbol in symbols:
        try:
            try:
                fetch_stockanalysis_data(symbol, force_refresh=True)
            except TypeError:
                try:
                    fetch_stockanalysis_data(symbol, refresh=True)
                except TypeError:
                    fetch_stockanalysis_data(symbol)

            refreshed.append(symbol)

        except Exception:
            continue

    if not refreshed:
        return "StockAnalysis checked, but no symbols refreshed."

    return "StockAnalysis refreshed for: " + ", ".join(refreshed)


def build_tradeplans_step() -> str:
    module = importlib.import_module("src.reports.tradeplans_report")
    func = getattr(module, "build_tradeplans_report")

    try:
        report = func(limit=5)
    except TypeError:
        report = func()

    return f"Trade plans built ({len(str(report))} chars)."


def build_allocation_step() -> str:
    from src.reports.allocation_report import build_allocation_report

    report = build_allocation_report()

    return f"Allocation snapshot built ({len(str(report))} chars)."


def build_daily_report_step() -> str:
    from src.reports.daily_report import build_daily_report

    report = build_daily_report()

    if not str(report).strip():
        raise RuntimeError("Daily report returned empty output.")

    return report


def validate_daily_report(report: str) -> str:
    missing = [term for term in REQUIRED_DAILY_REPORT_TERMS if term not in report]

    if missing:
        raise RuntimeError("Daily report missing: " + ", ".join(missing))

    return "Daily report quality validation passed."


def run_daily_agent(dry_run: bool = False) -> dict[str, Any]:
    started_at = utc_now()
    steps: list[dict[str, Any]] = []
    report = ""

    os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0" if dry_run else "1")

    if dry_run:
        add_step(steps, "News Intelligence", "skip", "Skipped during dry run.")
        add_step(steps, "Alert Monitor", "skip", "Skipped during dry run.")
        add_step(steps, "StockAnalysis Refresh", "skip", "Skipped during dry run.")
    else:
        run_step(steps, "News Intelligence", refresh_news_intelligence)
        run_step(steps, "Alert Monitor", refresh_alert_monitor)
        run_step(steps, "StockAnalysis Refresh", refresh_stockanalysis_top_names)

    run_step(steps, "Trade Plans", build_tradeplans_step)
    run_step(steps, "Portfolio Allocation", build_allocation_step)

    report_result = run_step(
        steps,
        "Daily Report Build",
        build_daily_report_step,
        critical=True,
    )

    if isinstance(report_result, str):
        report = report_result

    if report:
        run_step(
            steps,
            "Quality Review",
            lambda: validate_daily_report(report),
            critical=True,
        )
    else:
        add_step(
            steps,
            "Quality Review",
            "fail",
            "Daily report was not available for validation.",
            critical=True,
        )

    critical_failures = [
        step for step in steps
        if step.get("critical") and step.get("status") == "fail"
    ]

    success = not critical_failures

    status = {
        "success": success,
        "last_run": started_at,
        "completed_at": utc_now(),
        "dry_run": dry_run,
        "report_characters": len(report),
        "message": "Daily agent completed successfully." if success else "Daily agent completed with errors.",
        "steps": steps,
        "report": report,
    }

    save_daily_agent_status(status)

    return status


def format_daily_agent_result(status: dict[str, Any]) -> str:
    success = bool(status.get("success"))
    title = "Smart Money Daily Agent"
    result = "PASS" if success else "FAIL"

    lines = [
        title,
        f"Status: {result}",
        f"Last Run: {status.get('last_run') or 'Not available'}",
        f"Report Characters: {status.get('report_characters', 0)}",
        "",
        "Workflow",
    ]

    for step in status.get("steps", []):
        marker = {
            "pass": "PASS",
            "fail": "FAIL",
            "skip": "SKIP",
        }.get(step.get("status"), str(step.get("status", "")).upper())

        lines.append(f"- {marker}: {step.get('name')} - {step.get('detail')}")

    lines.extend(
        [
            "",
            "Next Commands",
            "/brief",
            "/report",
            "/allocation",
            "/tradeplans",
            "/contextstatus",
            "/quality",
            "",
            "Research only. Not financial advice.",
        ]
    )

    return "\n".join(lines)
