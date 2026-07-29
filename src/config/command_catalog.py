COMMAND_CATALOG_VERSION = "v1.2"


CORE_COMMANDS = [
    ("/brief", "Daily market brief"),
    ("/stock SYMBOL", "Stock snapshot"),
    ("/watch", "Watchlist"),
    ("/top10", "Top 20 Smart Money ideas"),
    ("/macro", "Global market context"),
    ("/themes", "Active market themes"),
    ("/calendar", "Weekly macro and earnings calendar"),
    ("/quality", "Report quality check"),
    ("/snapshot", "Fast one-screen market snapshot"),
]


DAILY_REPORT_COMMANDS = [
    ("/brief", "Daily market brief"),
    ("/report", "Daily report legacy alias"),
    ("/quality", "Report quality check"),
    ("/reportcheck", "Report quality check legacy alias"),
    ("/snapshot", "Fast one-screen market snapshot"),
    ("/testdaily", "Test daily report"),
    ("/dailycheck", "Daily report delivery check"),
    ("/senddaily", "Send daily report now"),
]


STOCK_RESEARCH_COMMANDS = [
    ("/stock SYMBOL", "Stock snapshot"),
    ("/ticker SYMBOL", "Stock snapshot legacy alias"),
    ("/quote SYMBOL", "Quote snapshot"),
    ("/market SYMBOL", "Market context"),
    ("/scorecard SYMBOL", "Smart Money scorecard"),
    ("/risk SYMBOL", "Risk view"),
    ("/earnings SYMBOL", "Earnings view"),
    ("/volume SYMBOL", "Volume analysis"),
    ("/analyst SYMBOL", "Analyst view"),
]


THEME_COMMANDS = [
    ("/themes", "Active market themes"),
    ("/defense", "Defense and AI warfare watch"),
    ("/growth", "Growth ideas"),
    ("/dividends", "Dividend ideas"),
    ("/portfolio", "Portfolio view"),
    ("/undervalued", "Undervalued screen"),
]


MARKET_CONTEXT_COMMANDS = [
    ("/macro", "Global market context"),
    ("/global", "Global market context legacy alias"),
    ("/headlines", "Market headlines"),
    ("/marketbrief", "Market brief"),
    ("/calendar", "Weekly macro and earnings calendar"),
    ("/weeklycalendar", "Weekly macro and earnings calendar legacy alias"),
    ("/weekahead", "Week ahead"),
    ("/quarterly", "Quarterly report"),
    ("/quarterlyreport", "Quarterly report legacy alias"),
]


SMART_MONEY_COMMANDS = [
    ("/smartmoney", "Smart money signals"),
    ("/conviction", "High-conviction ideas"),
    ("/congress", "Congressional trading"),
    ("/insiders", "Insider activity"),
    ("/sec", "SEC filings"),
    ("/filing SYMBOL", "Filing lookup"),
]


ADMIN_COMMANDS = [
    ("/deploycheck", "Deployment health check"),
    ("/securitycheck", "Security check"),
    ("/status", "Bot status"),
    ("/ping", "Ping check"),
    ("/diagnostics", "Diagnostics"),
    ("/health", "Health check"),
    ("/system", "System status"),
    ("/version", "Version"),
    ("/versionnotes", "Release notes"),
    ("/backup", "Backup"),
    ("/logs", "Logs"),
    ("/restart", "Restart bot"),
    ("/clearcache", "Clear cache"),
]


ALIASES = [
    ("/brief", "/report"),
    ("/stock", "/ticker"),
    ("/watch", "/watchlist"),
    ("/macro", "/global"),
    ("/calendar", "/weeklycalendar"),
    ("/quality", "/reportcheck"),
]


def format_command_group(title: str, commands: list[tuple[str, str]]) -> str:
    lines = [title]

    for command, description in commands:
        lines.append(f"{command} - {description}")

    return "\n".join(lines)


def format_aliases() -> str:
    lines = ["Aliases"]

    for alias, target in ALIASES:
        lines.append(f"{alias} = {target}")

    return "\n".join(lines)


def build_commands_menu_text() -> str:
    return """

🤖 Smart Money AI Commands

{core}

Daily Report
{daily}

Stock Research
{stock}

Themes
{themes}

Smart Money Intelligence
{smart_money}

Market Context
{market}

Admin / System
{admin}

{aliases}

Research only. Not financial advice.
""".format(
        core=format_command_group("Core Commands", CORE_COMMANDS),
        daily="\n".join(f"{cmd} - {desc}" for cmd, desc in DAILY_REPORT_COMMANDS),
        stock="\n".join(f"{cmd} - {desc}" for cmd, desc in STOCK_RESEARCH_COMMANDS),
        themes="\n".join(f"{cmd} - {desc}" for cmd, desc in THEME_COMMANDS),
        smart_money="\n".join(f"{cmd} - {desc}" for cmd, desc in SMART_MONEY_COMMANDS),
        market="\n".join(f"{cmd} - {desc}" for cmd, desc in MARKET_CONTEXT_COMMANDS),
        admin="\n".join(f"{cmd} - {desc}" for cmd, desc in ADMIN_COMMANDS),
        aliases=format_aliases(),
    ).strip()


def build_help_text() -> str:
    core_lines = "\n".join(
        f"{command} - {description}"
        for command, description in CORE_COMMANDS
    )

    return f"""
🤖 Smart Money AI Help

Start here:
{core_lines}

/versionnotes - What changed in the current release
/commands - Full command menu

Useful examples:
/brief
/stock NVDA
/scorecard PLTR
/volume AMD
/calendar
/quality

Research only. Not financial advice.
""".strip()


def get_primary_commands() -> list[tuple[str, str]]:
    return CORE_COMMANDS


def get_version_feature_lines() -> list[str]:
    return [
        "Command consolidation",
        "Primary command set",
        "Legacy aliases preserved",
        "Shared command catalog",
        "Cleaner help and commands menu",
        "Foundation for v1.2 routing",
    ]