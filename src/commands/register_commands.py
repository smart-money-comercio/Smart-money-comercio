from src.commands.daily_agent_commands import agentstatus_command, rundailyagent_command
from telegram.ext import CommandHandler

from src.commands.admin_commands import (
    admin_command,
    clearcache,
    diagnostics_command,
    ping_command,
    status_command,
)
from src.commands.analyst_commands import analyst_command
from src.commands.backup_commands import backup_command
from src.commands.restart_commands import restart_command
from src.commands.basic_commands import (
    defense,
    report,
    start,
)
from src.commands.daily_report_send_commands import (
    dailycheck_command,
    senddaily_command,
    testdaily_command,
)
from src.commands.deploycheck_commands import deploycheck_command
from src.commands.allocation_commands import allocation_command
from src.commands.global_commands import global_market
from src.commands.versionnotes_commands import versionnotes_command
from src.commands.contextstatus_commands import contextstatus_command, summarypreview_command
from src.commands.headlines_commands import headlines
from src.commands.snapshot_commands import snapshot_command 
from src.commands.alertsettings_commands import alertpreset_command, alertsettings_command
from src.commands.themes_commands import themes_command
from src.commands.health_commands import (
    health,
    system_status,
    version,
)
from src.commands.help_commands import admin_command, commands_command, help_command
from src.commands.intelligence_commands import (
    congress,
    conviction,
    insiders,
    smartmoney,
)
from src.commands.logs_commands import logs_command
from src.commands.market_commands import (
    earnings,
    market,
    quote,
    risk,
    scorecard,
    ticker,
)
from src.commands.marketbrief_commands import marketbrief_command
from src.commands.menu_commands import commands_menu
from src.commands.portfolio_commands import (
    dividends,
    growth,
    portfolio,
)
from src.commands.quarterly_commands import quarterly_command
from src.commands.reportcheck_commands import reportcheck_command
from src.commands.tradeplan_commands import tradeplan_command
from src.commands.screener_commands import undervalued
from src.commands.sec_commands import (
    filing,
    sec,
)
from src.commands.securitycheck_commands import securitycheck_command
from src.commands.top10_commands import top10
from src.commands.volume_commands import volume
from src.commands.watchlist_commands import watchlist_command
from src.commands.alerts_commands import alerts_command
from src.commands.dailyalerts_commands import dailyalerts_command
from src.commands.alertstatus_commands import alertstatus_command, alertrules_command
from src.commands.stockanalysis_commands import stockdata_command
from src.commands.tradeplans_commands import tradeplans_command
from src.commands.weekly_calendar_commands import weeklycalendar_command
from src.commands.newsintel_commands import (
macronews_command,
    newsintel_command,
    newsmemory_command,
    tickernews_command,
)


from src.commands.agentlog_commands import agentlog_command

def register_commands(app):
    # Core
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("commands", commands_command))
    app.add_handler(CommandHandler("command", commands_command))

    # Health / admin
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("system", system_status))
    app.add_handler(CommandHandler("version", version))
    app.add_handler(CommandHandler("versionnotes", versionnotes_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("diagnostics", diagnostics_command))
    app.add_handler(CommandHandler("clearcache", clearcache))
    app.add_handler(CommandHandler("deploycheck", deploycheck_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("restart", restart_command))
    app.add_handler(CommandHandler("securitycheck", securitycheck_command))
    app.add_handler(CommandHandler("security", securitycheck_command))

    # Daily report
    app.add_handler(CommandHandler("brief", report))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("snapshot", snapshot_command))
    app.add_handler(CommandHandler("quality", reportcheck_command))
    app.add_handler(CommandHandler("reportcheck", reportcheck_command))
    app.add_handler(CommandHandler("allocation", allocation_command))
    app.add_handler(CommandHandler("agentstatus", agentstatus_command))
    app.add_handler(CommandHandler("agentlog", agentlog_command))
    app.add_handler(CommandHandler("rundailyagent", rundailyagent_command))

    app.add_handler(CommandHandler("senddaily", senddaily_command))
    app.add_handler(CommandHandler("testdaily", testdaily_command))
    app.add_handler(CommandHandler("dailycheck", dailycheck_command))

    # Research / rankings
    app.add_handler(CommandHandler("top10", top10))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("defense", defense))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("dividends", dividends))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("themes", themes_command))
    app.add_handler(CommandHandler("undervalued", undervalued))

    # Market intelligence
    app.add_handler(CommandHandler("global", global_market))
    app.add_handler(CommandHandler("headlines", headlines))
    app.add_handler(CommandHandler("newsintel", newsintel_command))
    app.add_handler(CommandHandler("contextstatus", contextstatus_command))
    app.add_handler(CommandHandler("summarypreview", summarypreview_command))
    app.add_handler(CommandHandler("macronews", macronews_command))
    app.add_handler(CommandHandler("tickernews", tickernews_command))
    app.add_handler(CommandHandler("newsmemory", newsmemory_command))
    app.add_handler(CommandHandler("marketbrief", marketbrief_command))
    app.add_handler(CommandHandler("weeklycalendar", weeklycalendar_command))
    app.add_handler(CommandHandler("weekahead", weeklycalendar_command))
    app.add_handler(CommandHandler("quarterly", quarterly_command))
    app.add_handler(CommandHandler("quarterlyreport", quarterly_command))

    # Ticker tools
    app.add_handler(CommandHandler("tradeplan", tradeplan_command))
    app.add_handler(CommandHandler("tradeplans", tradeplans_command))
    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("stockdata", stockdata_command))
    app.add_handler(CommandHandler("quote", quote))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CommandHandler("volume", volume))
    app.add_handler(CommandHandler("scorecard", scorecard))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("analyst", analyst_command))

    # Smart money / filings
    app.add_handler(CommandHandler("conviction", conviction))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("dailyalerts", dailyalerts_command))
    app.add_handler(CommandHandler("alertstatus", alertstatus_command))
    app.add_handler(CommandHandler("alertrules", alertrules_command))
    app.add_handler(CommandHandler("alertsettings", alertsettings_command))
    app.add_handler(CommandHandler("alertpreset", alertpreset_command))
    app.add_handler(CommandHandler("congress", congress))
    app.add_handler(CommandHandler("insiders", insiders))
    app.add_handler(CommandHandler("sec", sec))
    app.add_handler(CommandHandler("filing", filing))

    # Friendly aliases
    app.add_handler(CommandHandler("stock", ticker))
    app.add_handler(CommandHandler("calendar", weeklycalendar_command))
    app.add_handler(CommandHandler("watch", watchlist_command))
    app.add_handler(CommandHandler("macro", global_market))

 
