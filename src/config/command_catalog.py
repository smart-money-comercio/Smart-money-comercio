COMMAND_CATALOG_VERSION = "v1.4"

START_COMMANDS = [
    ("/start", "Start bot"),
    ("/help", "Help menu"),
    ("/commands", "Full command menu"),
    ("/admin", "Admin menu"),
]

CORE_COMMANDS = [
    ("/brief", "Daily market brief"),
    ("/dailyalerts", "Daily alert digest"),
    ("/alerts", "Full alert monitor"),
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
]


START_COMMANDS = [
    ("/start", "Start bot"),
    ("/help", "Help menu"),
    ("/commands", "Full command menu"),
    ("/admin", "Admin menu"),
]


DAILY_REPORT_COMMANDS = [
    ("/brief", "Daily market brief"),
    ("/report", "Daily report legacy alias"),
    ("/snapshot", "Fast one-screen market snapshot"),
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
    ("/global", "Global macro intelligence"),
    ("/macro", "Global macro legacy alias"),
    ("/headlines", "Market headlines"),
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
    ("/conviction", "High-conviction overlap candidates"),
    ("/alertstatus", "Current alert monitor state, queues, and latest scan"),
    ("/alertrules", "Visible alert thresholds and environment overrides"),
    ("/alerts", "Full alert monitor for conviction, risk, macro, filing, catalyst, and validation changes"),
    ("/dailyalerts", "Compressed daily alert digest for critical changes, warnings, macro alerts, and first action"),
    ("/congress", "Congressional trading"),
    ("/insiders", "Insider activity"),
    ("/sec SYMBOL", "SEC disclosure intelligence"),
    ("/filing SYMBOL", "Filing lookup and thesis impact"),
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

Start / Menu
{start}

Daily Report / Alerts
{daily}

Stock Research
{stock}

Watchlist
{watchlist}

Themes / Portfolio
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
        start="\n".join(f"{cmd} - {desc}" for cmd, desc in START_COMMANDS),
        daily="\n".join(f"{cmd} - {desc}" for cmd, desc in DAILY_REPORT_COMMANDS),
        stock="\n".join(f"{cmd} - {desc}" for cmd, desc in STOCK_RESEARCH_COMMANDS),
        watchlist="\n".join(f"{cmd} - {desc}" for cmd, desc in WATCHLIST_COMMANDS),
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
/dailyalerts
/alerts
/smartmoney
/conviction
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
        "v1.4 alert monitoring foundation",
        "/alerts full alert monitor",
        "/dailyalerts compressed daily alert digest",
        "v1.3 intelligence command centers preserved",
        "Primary command catalog refreshed",
        "Legacy aliases preserved",
        "Shared command catalog for help, commands, version, and Telegram menu",
    ]