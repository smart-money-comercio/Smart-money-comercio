from telegram.ext import CommandHandler

from src.commands.basic_commands import (
    start,
    help_command,
    report,
    top10,
    watchlist,
    defense,
)

from src.commands.portfolio_commands import (
    growth,
    dividends,
    portfolio,
)

from src.commands.market_commands import (
    ticker,
    quote,
    market,
    earnings,
    scorecard,
    risk,
)


def register_commands(app, commands):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("report", report))

    app.add_handler(CommandHandler("top10", top10))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("defense", defense))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("dividends", dividends))
    app.add_handler(CommandHandler("portfolio", portfolio))

    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("quote", quote))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CommandHandler("scorecard", scorecard))
    app.add_handler(CommandHandler("risk", risk))

    app.add_handler(CommandHandler("conviction", commands["conviction"]))
    app.add_handler(CommandHandler("smartmoney", commands["smartmoney"]))
    app.add_handler(CommandHandler("undervalued", commands["undervalued"]))

    app.add_handler(CommandHandler("congress", commands["congress"]))
    app.add_handler(CommandHandler("insiders", commands["insiders"]))
    app.add_handler(CommandHandler("sec", commands["sec"]))
    app.add_handler(CommandHandler("filing", commands["filing"]))