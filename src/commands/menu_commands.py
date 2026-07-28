from telegram import Update
from telegram.ext import ContextTypes


COMMANDS_TEXT = """
🤖 Smart Money AI Commands

Core Commands
/brief - Daily market brief
/stock SYMBOL - Stock snapshot
/watch - Watchlist
/top10 - Top 20 Smart Money ideas
/macro - Global market context
/calendar - Weekly macro and earnings calendar
/quality - Daily report quality check

Daily Report
/report - Daily report
/reportcheck - Report quality check
/testdaily - Test daily report
/dailycheck - Daily report delivery check
/senddaily - Send daily report now

Stock Research
/ticker SYMBOL - Stock snapshot
/quote SYMBOL - Quote snapshot
/market SYMBOL - Market context
/scorecard SYMBOL - Smart Money scorecard
/risk SYMBOL - Risk view
/earnings SYMBOL - Earnings view
/volume SYMBOL - Volume analysis
/analyst SYMBOL - Analyst view

Themes
/defense - Defense and AI warfare watch
/growth - Growth ideas
/dividends - Dividend ideas
/portfolio - Portfolio view
/undervalued - Undervalued screen

Smart Money Intelligence
/smartmoney - Smart money signals
/conviction - High-conviction ideas
/congress - Congressional trading
/insiders - Insider activity
/sec - SEC filings
/filing SYMBOL - Filing lookup

Market Context
/marketbrief - Market brief
/global - Global market context
/headlines - Market headlines
/weeklycalendar - Weekly macro and earnings calendar
/weekahead - Week ahead
/quarterly - Quarterly report
/quarterlyreport - Quarterly report

Admin / System
/deploycheck - Deployment health check
/securitycheck - Security check
/status - Bot status
/ping - Ping check
/diagnostics - Diagnostics
/health - Health check
/system - System status
/version - Version
/backup - Backup
/logs - Logs
/restart - Restart bot
/clearcache - Clear cache

Aliases
/brief = /report
/stock = /ticker
/calendar = /weeklycalendar
/quality = /reportcheck
/watch = /watchlist
/macro = /global

Research only. Not financial advice.
""".strip()


async def commands_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(COMMANDS_TEXT)