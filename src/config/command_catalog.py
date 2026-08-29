COMMAND_CATALOG_VERSION = "v1.4"


START_COMMANDS = [
    ("/start", "Start bot"),
    ("/help", "Help menu"),
    ("/commands", "Full command menu"),
    ("/admin", "Admin menu"),
]


CORE_COMMANDS = [
    ("/brief", "Daily market brief"),
    ("/headlines", "Fast market headline tape"),
    ("/newsintel", "Evolving market-news intelligence"),
    ("/newsmemory", "What the news engine has learned"),
    ("/dailyalerts", "Daily alert digest"),
    ("/alerts", "Full alert monitor"),
    ("/alertstatus", "Latest recorded alert state"),
    ("/alertsettings", "Current alert thresholds, environment overrides, and detected preset"),
    ("/alertpreset MODE", "Show conservative, balanced, or aggressive alert preset overrides"),
    ("/smartmoney", "Smart Money command center"),
    ("/conviction", "High-conviction ideas"),
    ("/snapshot", "Fast one-screen market snapshot"),
    ("/stock SYMBOL", "Stock intelligence"),
    ("/watchlist", "Watchlist"),
    ("/top10", "Top 20 Smart Money ideas"),
    ("/portfolio", "Portfolio intelligence"),
    ("/global", "Global macro intelligence"),
    ("/quality", "Report quality check"),
    ("/contextstatus", "Provider status for the Smart Money Summary"),
    ("/summarypreview", "Preview the current Smart Money Summary"),
]


DAILY_REPORT_COMMANDS = [
    ("/brief", "Daily market brief"),
    ("/report", "Daily report legacy alias"),
    ("/snapshot", "Fast one-screen market snapshot"),
    ("/headlines", "Fast market headline tape"),
    ("/newsintel", "Evolving market-news intelligence"),
    ("/dailyalerts", "Compressed daily alert digest"),
    ("/alerts", "Full alert monitor"),
    ("/quality", "Report quality check"),
    ("/reportcheck", "Report quality check legacy alias"),
    ("/testdaily", "Test daily report"),
    ("/dailycheck", "Daily report delivery check"),
    ("/senddaily", "Send daily report now"),
]


STOCK_RESEARCH_COMMANDS = [
    ("/stock SYMBOL", "Stock intelligence"),
    ("/stockdata SYMBOL", "StockAnalysis fundamentals, valuation, financials, balance sheet, cash-flow, and analyst rating snapshot"),
    ("/ticker SYMBOL", "Stock intelligence legacy alias"),
    ("/tickernews SYMBOL", "Ticker-specific news intelligence"),
    ("/quote SYMBOL", "Quote snapshot"),
    ("/market SYMBOL", "Market context"),
    ("/scorecard SYMBOL", "Smart Money scorecard"),
    ("/risk SYMBOL", "Risk intelligence"),
    ("/earnings SYMBOL", "Earnings catalyst intelligence"),
    ("/volume SYMBOL", "Volume and money-flow intelligence"),
    ("/analyst SYMBOL", "Analyst consensus intelligence"),
    ("/sec SYMBOL", "SEC disclosure intelligence"),
    ("/filing SYMBOL", "Filing lookup and thesis impact"),
]


WATCHLIST_COMMANDS = [
    ("/watchlist", "Watchlist command center"),
    ("/watch", "Watchlist legacy alias"),
]


THEME_COMMANDS = [
    ("/themes", "Active market themes"),
    ("/defense", "Defense and AI warfare intelligence"),
    ("/growth", "Growth ideas"),
    ("/dividends", "Dividend ideas"),
    ("/portfolio", "Portfolio intelligence"),
    ("/undervalued", "Undervalued screen"),
]


MARKET_CONTEXT_COMMANDS = [
    ("/contextstatus", "Provider status for the Smart Money Summary"),
    ("/summarypreview", "Preview the current Smart Money Summary"),
    ("/global", "Global macro intelligence"),
    ("/macro", "Global macro legacy alias"),
    ("/headlines", "Fast market headline tape"),
    ("/newsintel", "Evolving market-news intelligence"),
    ("/macronews", "Macro-only news intelligence"),
    ("/tickernews SYMBOL", "Ticker-specific news intelligence"),
    ("/newsmemory", "What the news engine has learned"),
    ("/marketbrief", "Market brief"),
    ("/calendar", "Weekly macro and earnings calendar"),
    ("/weeklycalendar", "Weekly macro and earnings calendar legacy alias"),
    ("/weekahead", "Week ahead"),
    ("/quarterly", "Quarterly report"),
    ("/quarterlyreport", "Quarterly report legacy alias"),
]


SMART_MONEY_COMMANDS = [
    ("/smartmoney", "Smart Money command center"),
    ("/conviction", "Highest conviction opportunities"),
    ("/undervalued", "Undervalued opportunities"),
    ("/congress", "Congress trading intelligence"),
    ("/insiders", "Insider trading intelligence"),
    ("/sec", "SEC filing intelligence"),
    ("/filing SYMBOL", "Ticker SEC filing intelligence"),
    ("/alerts", "Full Smart Money AI alert monitor"),
    ("/dailyalerts", "Compressed daily alert digest"),
    ("/alertstatus", "Latest recorded alert state"),
    ("/alertrules", "Alert rule thresholds and environment settings"),
    ("/alertsettings", "Current alert thresholds, environment overrides, and detected preset"),
    ("/alertpreset MODE", "Show conservative, balanced, or aggressive alert preset overrides"),
]


ADMIN_COMMANDS = [
    ("/deploycheck", "Deployment health check"),
    ("/securitycheck", "Security check"),
    ("/security", "Security check alias"),
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
    ("/security", "/securitycheck"),
]


COMMAND_GROUPS = [
    ("Core Commands", CORE_COMMANDS),
    ("Start / Menu", START_COMMANDS),
    ("Daily Report / Alerts", DAILY_REPORT_COMMANDS),
    ("Stock Research", STOCK_RESEARCH_COMMANDS),
    ("Watchlist", WATCHLIST_COMMANDS),
    ("Themes / Portfolio", THEME_COMMANDS),
    ("Smart Money Intelligence", SMART_MONEY_COMMANDS),
    ("Market Context", MARKET_CONTEXT_COMMANDS),
    ("Admin / System", ADMIN_COMMANDS),
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
    sections = ["🤖 Smart Money AI Commands"]

    for title, commands in COMMAND_GROUPS:
        sections.append(format_command_group(title, commands))

    sections.append(format_aliases())
    sections.append("Research only. Not financial advice.")

    return "\n\n".join(sections).strip()


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
/headlines
/newsintel
/newsmemory
/dailyalerts
/alerts
/alertstatus
/smartmoney
/conviction
/brief
/stock NVDA
/tickernews NVDA
/scorecard PLTR
/volume AMD
/calendar
/quality

Research only. Not financial advice.
""".strip()


def get_primary_commands() -> list[tuple[str, str]]:
    return CORE_COMMANDS


def get_all_command_groups() -> list[tuple[str, list[tuple[str, str]]]]:
    return COMMAND_GROUPS


def get_all_commands() -> list[tuple[str, str]]:
    commands = []
    seen = set()

    for _title, group in COMMAND_GROUPS:
        for command, description in group:
            command_key = command.split()[0].lower()

            if command_key in seen:
                continue

            seen.add(command_key)
            commands.append((command, description))

    return commands


def get_version_feature_lines() -> list[str]:
    return [
        "v1.4 alert monitoring foundation",
        "/alerts full alert monitor",
        "/dailyalerts compressed daily alert digest",
        "/alertstatus latest alert state",
        "/alertsettings active alert settings readout",
        "/alertpreset conservative, balanced, and aggressive alert recipes",
        "/headlines upgraded fast market headline tape",
        "/newsintel evolving market-news intelligence",
        "/macronews macro-only news intelligence",
        "/tickernews SYMBOL ticker-specific news intelligence",
        "/newsmemory persistent news intelligence memory",
        "StockAnalysis integration preserved",
        "v1.3 intelligence command centers preserved",
        "Primary command catalog refreshed",
        "Legacy aliases preserved",
        "Shared command catalog for help, commands, version, and Telegram menu",
    ]