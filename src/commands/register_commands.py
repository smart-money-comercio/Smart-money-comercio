from telegram.ext import CommandHandler

from src.commands.admin_commands import admin_command

from src.commands.admin_commands import clearcache, admin_command, status_command, ping_command, diagnostics_command

from src.commands.daily_report_send_commands import senddaily_command, testdaily_command

from src.commands.help_commands import help_command, commands_menu

from src.commands.securitycheck_commands import securitycheck_command

from src.commands.basic_commands import (
    start,
    help_command,
    report,
    top10,
    defense,
)

from src.commands.portfolio_commands import (
    growth,
    dividends,
    portfolio,
)

from src.commands.watchlist_commands import watchlist_command

from src.commands.deploycheck_commands import deploycheck_command

from src.commands.backup_commands import backup_command

from src.commands.logs_commands import logs_command

from src.commands.restart_commands import restart_command

from src.commands.market_commands import (
    ticker,
    quote,
    market,
    earnings,
    scorecard,
    risk,
)

from src.commands.marketbrief_commands import marketbrief_command

from src.commands.intelligence_commands import (
    congress,
    insiders,
    smartmoney,
    conviction,
)

from src.commands.screener_commands import undervalued

from src.commands.sec_commands import (
    sec,
    filing,
)

from src.commands.health_commands import (
    health,
    system_status,
    version,
)

from src.commands.menu_commands import commands_menu


def register_commands(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("commands", commands_menu))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("system", system_status))
    app.add_handler(CommandHandler("version", version))
    app.add_handler(CommandHandler("clearcache", clearcache))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("diagnostics", diagnostics_command))
    app.add_handler(CommandHandler("deploycheck", deploycheck_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("restart", restart_command))
    app.add_handler(CommandHandler("securitycheck", securitycheck_command))

    app.add_handler(CommandHandler("top10", top10))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("defense", defense))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("dividends", dividends))
    app.add_handler(CommandHandler("portfolio", portfolio))

    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("quote", quote))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("marketbrief", marketbrief_command))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CommandHandler("scorecard", scorecard))
    app.add_handler(CommandHandler("risk", risk))

    app.add_handler(CommandHandler("conviction", conviction))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("undervalued", undervalued))

    app.add_handler(CommandHandler("congress", congress))
    app.add_handler(CommandHandler("insiders", insiders))
    app.add_handler(CommandHandler("sec", sec))
    app.add_handler(CommandHandler("filing", filing))

    app.add_handler(CommandHandler("senddaily", senddaily_command))
    app.add_handler(CommandHandler("testdaily", testdaily_command))