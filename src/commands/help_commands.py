from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import is_admin


PUBLIC_HELP_TEXT = """
🤖 Smart Money AI Bot

Available Commands

General
/start - Start the bot
/help - Show help menu
/commands - Show full command list

Market Research
/report - Generate Smart Money AI market report
/top10 - Show top ranked opportunities
/quote SYMBOL - Get a stock quote
/market SYMBOL - Get market data
/ticker SYMBOL - Quick ticker lookup
/scorecard SYMBOL - Show Smart Money scorecard
/risk SYMBOL - Show risk profile

Examples
/quote NVDA
/market AAPL
/scorecard MSFT
/risk TSLA

Watchlist
/watchlist - Show watchlist help
/watchlist list - Show current watchlist
/watchlist add AAPL MSFT NVDA - Add symbols
/watchlist remove TSLA - Remove symbol
/watchlist report - Full watchlist report
/watchlist prices - Watchlist prices
/watchlist movers - Biggest gainers and losers
/watchlist alerts - Manual watchlist alert scan

Research Categories
/defense - Defense sector opportunities
/growth - Growth stock opportunities
/dividends - Dividend stock opportunities
/portfolio - Portfolio-style summary

Smart Money Signals
/congress - Congressional trading signals
/insiders - Insider trading signals
/smartmoney - Smart money summary
/conviction - High conviction opportunities
/undervalued - Undervalued opportunities

SEC Research
/sec SYMBOL - SEC filing summary
/filing SYMBOL - Latest filing lookup

Admin-only commands are shown to authorized admins.
""".strip()


ADMIN_HELP_TEXT = """
Admin / Production Commands

Health & Diagnostics
/deploycheck - Production health check
/status - Bot status
/ping - Bot ping test
/diagnostics - Environment diagnostics
/health - Health check
/system - System info
/version - Bot version

Reports
/senddaily - Send daily report to configured channel
/testdaily - Send daily report to current admin chat

Maintenance
/backup - Create manual server backup
/logs - Show recent service logs
/logs 80 - Show last 80 service log lines
/restart - Restart production bot
/clearcache - Clear loaded caches
/admin - Show current admin/chat info

Production Notes
• Code updates are done from laptop + GitHub + SSH.
• /update was intentionally skipped for safety.
• Local bot testing requires stopping the DigitalOcean service first.
""".strip()


COMMANDS_TEXT = """
📋 Smart Money AI Commands

General
/start
/help
/commands

Market
/report
/top10
/quote SYMBOL
/market SYMBOL
/ticker SYMBOL
/scorecard SYMBOL
/risk SYMBOL
/earnings SYMBOL

Watchlist
/watchlist
/watchlist list
/watchlist add SYMBOL
/watchlist remove SYMBOL
/watchlist clear
/watchlist reset
/watchlist report
/watchlist prices
/watchlist summary
/watchlist movers
/watchlist leaders
/watchlist leaderboard
/watchlist alerts
/watchlist alerts 2.5

Research
/defense
/growth
/dividends
/portfolio
/congress
/insiders
/smartmoney
/conviction
/undervalued

SEC
/sec SYMBOL
/filing SYMBOL

Admin
/deploycheck
/status
/ping
/diagnostics
/health
/system
/version
/senddaily
/testdaily
/backup
/logs
/restart
/clearcache
/admin
""".strip()


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text(
            f"{PUBLIC_HELP_TEXT}\n\n{ADMIN_HELP_TEXT}"
        )
        return

    await update.message.reply_text(PUBLIC_HELP_TEXT)


async def commands_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text(COMMANDS_TEXT)
        return

    public_commands = """
📋 Smart Money AI Commands

General
/start
/help
/commands

Market
/report
/top10
/quote SYMBOL
/market SYMBOL
/ticker SYMBOL
/scorecard SYMBOL
/risk SYMBOL
/earnings SYMBOL

Watchlist
/watchlist
/watchlist list
/watchlist add SYMBOL
/watchlist remove SYMBOL
/watchlist report
/watchlist prices
/watchlist summary
/watchlist movers
/watchlist alerts

Research
/defense
/growth
/dividends
/portfolio
/congress
/insiders
/smartmoney
/conviction
/undervalued

SEC
/sec SYMBOL
/filing SYMBOL
""".strip()

    await update.message.reply_text(public_commands)