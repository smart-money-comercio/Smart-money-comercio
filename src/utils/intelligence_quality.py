from dataclasses import dataclass
from typing import Callable


DEFAULT_SYMBOL = "NVDA"
TELEGRAM_SAFE_CHARS = 3900
TOP10_SAFE_CHARS = 12000
BRIEF_SAFE_CHARS = 6200


@dataclass
class CheckResult:
    name: str
    status: str
    chars: int = 0
    details: str = ""
    missing_sections: list[str] | None = None


def clean_symbol(symbol: str) -> str:
    return str(symbol or DEFAULT_SYMBOL).upper().replace("$", "").strip() or DEFAULT_SYMBOL


def has_bad_error_text(text: str) -> bool:
    lowered = str(text or "").lower()

    bad_markers = [
        "traceback",
        "status: unavailable right now",
        "importerror:",
        "nameerror:",
        "typeerror:",
        "syntaxerror:",
    ]

    return any(marker in lowered for marker in bad_markers)


def check_text_report(
    name: str,
    text: str,
    required_sections: list[str],
    max_chars: int,
) -> CheckResult:
    text = str(text or "").strip()
    missing = [section for section in required_sections if section not in text]

    if not text:
        return CheckResult(
            name=name,
            status="FAIL",
            chars=0,
            details="Report returned empty text.",
            missing_sections=required_sections,
        )

    if has_bad_error_text(text):
        return CheckResult(
            name=name,
            status="FAIL",
            chars=len(text),
            details="Report contains error/unavailable text.",
            missing_sections=missing,
        )

    if missing:
        return CheckResult(
            name=name,
            status="FAIL",
            chars=len(text),
            details="Missing required sections.",
            missing_sections=missing,
        )

    if len(text) > max_chars:
        return CheckResult(
            name=name,
            status="FAIL",
            chars=len(text),
            details=f"Report too long. Limit: {max_chars}.",
            missing_sections=[],
        )

    return CheckResult(
        name=name,
        status="PASS",
        chars=len(text),
        details="OK",
        missing_sections=[],
    )


def safe_build(name: str, builder: Callable[[], str]) -> tuple[str, str]:
    try:
        return builder(), ""
    except Exception as error:
        return "", f"{type(error).__name__}: {error}"


def check_evolving_report(
    name: str,
    builder: Callable[[], str],
    required_sections: list[str],
    max_chars: int = TELEGRAM_SAFE_CHARS,
) -> CheckResult:
    first_text, first_error = safe_build(name, builder)

    if first_error:
        return CheckResult(
            name=name,
            status="FAIL",
            chars=0,
            details=f"First build failed: {first_error}",
            missing_sections=required_sections,
        )

    second_text, second_error = safe_build(name, builder)

    if second_error:
        return CheckResult(
            name=name,
            status="FAIL",
            chars=len(first_text),
            details=f"Second build failed: {second_error}",
            missing_sections=required_sections,
        )

    result = check_text_report(
        name=name,
        text=second_text,
        required_sections=required_sections,
        max_chars=max_chars,
    )

    if result.status == "FAIL":
        return result

    evolving_markers = [
        "What Changed",
        "Evolving Analysis",
        "Evolving Read",
        "Ranking Changes",
    ]

    if not any(marker in second_text for marker in evolving_markers):
        return CheckResult(
            name=name,
            status="FAIL",
            chars=len(second_text),
            details="Missing evolving-analysis marker.",
            missing_sections=[],
        )

    return result


def check_standard_report(
    name: str,
    builder: Callable[[], str],
    required_sections: list[str],
    max_chars: int = TELEGRAM_SAFE_CHARS,
) -> CheckResult:
    text, error = safe_build(name, builder)

    if error:
        return CheckResult(
            name=name,
            status="FAIL",
            chars=0,
            details=f"Build failed: {error}",
            missing_sections=required_sections,
        )

    return check_text_report(
        name=name,
        text=text,
        required_sections=required_sections,
        max_chars=max_chars,
    )


def check_snapshot_import() -> CheckResult:
    try:
        import src.commands.snapshot_commands as snapshot_commands

        candidate_names = [
            "build_snapshot_report",
            "build_snapshot_text",
            "build_smart_money_snapshot",
            "build_snapshot",
        ]

        for name in candidate_names:
            builder = getattr(snapshot_commands, name, None)

            if callable(builder):
                text = builder()

                return check_text_report(
                    name="/snapshot",
                    text=text,
                    required_sections=[
                        "Smart Money AI Snapshot",
                        "Top Idea",
                        "Action Read",
                    ],
                    max_chars=TELEGRAM_SAFE_CHARS,
                )

        return CheckResult(
            name="/snapshot",
            status="PASS",
            chars=0,
            details="snapshot_commands import OK; no standalone snapshot builder found.",
            missing_sections=[],
        )

    except Exception as error:
        return CheckResult(
            name="/snapshot",
            status="FAIL",
            chars=0,
            details=f"snapshot import failed: {type(error).__name__}: {error}",
            missing_sections=[],
        )


def build_top10_report_safely(scores) -> str:
    from src.reports.top10_report import build_top10_report

    try:
        return build_top10_report(scores, limit=20, record_memory=False)
    except TypeError:
        return build_top10_report(scores, limit=20)


def run_intelligence_quality_check(symbol: str = DEFAULT_SYMBOL) -> dict:
    symbol = clean_symbol(symbol)

    from src.reports.daily_report import build_daily_report
    from src.reports.earnings_intelligence_report import build_earnings_intelligence_report
    from src.reports.analyst_intelligence_report import build_analyst_intelligence_report
    from src.reports.risk_intelligence_report import build_risk_intelligence_report
    from src.reports.portfolio_intelligence_report import build_portfolio_intelligence_report
    from src.reports.scorecard_intelligence_report import build_scorecard_intelligence_report
    from src.reports.stock_intelligence_report import build_stock_intelligence_report
    from src.reports.smartmoney_command_center_report import build_smartmoney_command_center_report
    from src.reports.defense_intelligence_report import build_defense_intelligence_report
    from src.reports.conviction_command_center_report import build_conviction_command_center_report
    from src.reports.volume_intelligence_report import build_volume_intelligence_report
    from src.reports.global_intelligence_report import build_global_intelligence_report
    from src.reports.filing_intelligence_report import build_filing_intelligence_report
    from src.scoring.scoring_engine import get_stock_scores

    results = []

    results.append(
        check_evolving_report(
            name="/stock",
            builder=lambda: build_stock_intelligence_report(symbol),
            required_sections=[
                "Stock Intelligence",
                "Live Tape",
                "What Changed",
                "Evolving Read",
                "Related Commands",
            ],
        )
    )

    results.append(
        check_standard_report(
            name="/scorecard",
            builder=lambda: build_scorecard_intelligence_report(symbol),
            required_sections=[
                "Smart Money Scorecard",
                "Score Components",
                "Interpretation",
                "Action Read",
                "Related Commands",
            ],
        )
    )

    results.append(
        check_standard_report(
            name="/risk",
            builder=lambda: build_risk_intelligence_report(symbol),
            required_sections=[
                "Risk Intelligence",
                "Main Risks",
                "What Would Reduce Risk",
                "What Would Increase Risk",
                "Risk Action",
            ],
        )
    )

    results.append(
        check_evolving_report(
            name="/volume",
            builder=lambda: build_volume_intelligence_report(symbol),
            required_sections=[
                "Volume Intelligence",
                "Live Tape",
                "Money-Flow Read",
                "What Changed",
                "Evolving Analysis",
                "Volume Action",
            ],
        )
    )

    results.append(
        check_evolving_report(
            name="/earnings",
            builder=lambda: build_earnings_intelligence_report(symbol),
            required_sections=[
                "Earnings / Catalyst Intelligence",
                "Catalyst Read",
                "What Changed",
                "Evolving Analysis",
                "What Would Confirm The Thesis",
                "Catalyst Action",
            ],
        )
    )

    results.append(
        check_evolving_report(
            name="/analyst",
            builder=lambda: build_analyst_intelligence_report(symbol),
            required_sections=[
                "Analyst Consensus Intelligence",
                "Analyst Targets",
                "Consensus Read",
                "Smart Money vs Wall Street",
                "What Changed",
                "Evolving Analysis",
                "Analyst Action",
            ],
        )
    )

    results.append(
        check_evolving_report(
            name="/filing",
            builder=lambda: build_filing_intelligence_report(symbol),
            required_sections=[
                "SEC / Filing Intelligence",
                "Filing Context",
                "Filing Read",
                "Disclosure Signals",
                "Portfolio Impact",
                "What Changed",
                "Evolving Analysis",
                "Filing Action",
            ],
        )
    )

    results.append(
        check_evolving_report(
            name="/portfolio",
            builder=build_portfolio_intelligence_report,
            required_sections=[
                "Portfolio Intelligence",
                "Portfolio Read",
                "Best Current Opportunities",
                "Highest-Risk Names",
                "Confirmation Queue",
                "Theme Exposure",
                "What Changed",
                "Evolving Analysis",
                "Portfolio Action",
            ],
            max_chars=12000,
        )
    )

    results.append(
        check_evolving_report(
            name="/defense",
            builder=lambda: build_defense_intelligence_report(force_refresh=False),
            required_sections=[
                "Defense / AI Warfare Intelligence",
                "Portfolio Read",
                "Official-Source Themes",
                "Official-Source Data Points",
                "Why This Matters",
                "Best Defense / AI Warfare Names",
                "What Changed",
                "Evolving Analysis",
                "Defense Action",
            ],
            max_chars=12000,
        )
    )

    results.append(
        check_evolving_report(
            name="/global",
            builder=lambda: build_global_intelligence_report(force_refresh=False),
            required_sections=[
                "Global Macro Intelligence",
                "Market Tape",
                "Official-Source Themes",
                "Official-Source Data Points",
                "Macro Pressure",
                "Portfolio Read",
                "What Changed",
                "Evolving Analysis",
                "Global Action",
            ],
            max_chars=12000,
        )
    )

    results.append(
        check_evolving_report(
            name="/smartmoney",
            builder=lambda: build_smartmoney_command_center_report(force_refresh=False),
            required_sections=[
                "Smart Money Command Center",
                "Executive Read",
                "Signal Summary",
                "Global Macro Overlay",
                "Macro Pressure",
                "Strongest Smart Money Signals",
                "Highest-Risk Names",
                "Validation Queue",
                "Defense / Policy Overlay",
                "What Changed",
                "Evolving Analysis",
                "Smart Money Action",
            ],
            max_chars=14000,
        )
    )

    results.append(
        check_evolving_report(
            name="/conviction",
            builder=lambda: build_conviction_command_center_report(force_refresh=False),
            required_sections=[
                "Conviction Command Center",
                "Executive Read",
                "Signal Summary",
                "Confirmed / Actionable Candidates",
                "Highest Conviction Watchlist",
                "Validation Queue",
                "Risk-Control Names",
                "Signal Overlap Matrix",
                "Macro / Defense Fit",
                "Congress / Insider Overlay",
                "What Changed",
                "Evolving Analysis",
                "Conviction Action",
            ],
            max_chars=14000,
        )
    )
    
    results.append(
        check_standard_report(
            name="/top10",
            builder=lambda: build_top10_report_safely(get_stock_scores()),
            required_sections=[
                "Top 20 Smart Money Ideas",
                "Top 20 Summary",
                "Action Buckets",
                "Ranking Changes",
                "Ideas",
            ],
            max_chars=TOP10_SAFE_CHARS,
        )
    )

    results.append(
        check_standard_report(
            name="/brief",
            builder=build_daily_report,
            required_sections=[
                "Smart Money AI Daily Report",
                "Executive Summary",
                "Trade Plan Snapshot",
                "Top Opportunities",
                "Smart Money Summary",
                "Action Checklist",
                "Portfolio Allocation Snapshot",
            ],
            max_chars=BRIEF_SAFE_CHARS,
        )
    )

    results.append(check_snapshot_import())

    failed = [result for result in results if result.status != "PASS"]

    return {
        "symbol": symbol,
        "status": "PASS" if not failed else "FAIL",
        "results": results,
        "failed": failed,
    }


def format_intelligence_quality_report(payload: dict) -> str:
    results = payload.get("results", [])
    failed = payload.get("failed", [])
    symbol = payload.get("symbol", DEFAULT_SYMBOL)
    status = payload.get("status", "FAIL")

    lines = [
        "Intelligence Quality Check",
        f"Status: {status}",
        f"Symbol: {symbol}",
        "",
        "Checks",
    ]

    for result in results:
        detail = result.details or "OK"

        if result.chars:
            lines.append(f"{result.status}: {result.name} — {result.chars} chars — {detail}")
        else:
            lines.append(f"{result.status}: {result.name} — {detail}")

        if result.missing_sections:
            lines.append("  Missing: " + ", ".join(result.missing_sections))

    if failed:
        lines.extend(
            [
                "",
                "Failures",
            ]
        )

        for result in failed:
            lines.append(f"• {result.name}: {result.details}")

            if result.missing_sections:
                lines.append("  Missing: " + ", ".join(result.missing_sections))

    lines.extend(
        [
            "",
            "Required Stack",
            "/stock → /scorecard → /risk → /volume → /earnings → /top10 → /brief",
        ]
    )

    return "\n".join(lines)