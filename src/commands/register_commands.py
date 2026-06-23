from telegram.ext import CommandHandler


def register_commands(app, commands):
    app.add_handler(CommandHandler("start", commands["start"]))
    app.add_handler(CommandHandler("help", commands["help"]))
    app.add_handler(CommandHandler("report", commands["report"]))

    app.add_handler(CommandHandler("top10", commands["top10"]))
    app.add_handler(CommandHandler("watchlist", commands["watchlist"]))
    app.add_handler(CommandHandler("defense", commands["defense"]))
    app.add_handler(CommandHandler("growth", commands["growth"]))
    app.add_handler(CommandHandler("dividends", commands["dividends"]))
    app.add_handler(CommandHandler("portfolio", commands["portfolio"]))

    app.add_handler(CommandHandler("ticker", commands["ticker"]))
    app.add_handler(CommandHandler("quote", commands["quote"]))
    app.add_handler(CommandHandler("market", commands["market"]))
    app.add_handler(CommandHandler("earnings", commands["earnings"]))
    app.add_handler(CommandHandler("scorecard", commands["scorecard"]))

    app.add_handler(CommandHandler("risk", commands["risk"]))
    app.add_handler(CommandHandler("conviction", commands["conviction"]))
    app.add_handler(CommandHandler("smartmoney", commands["smartmoney"]))
    app.add_handler(CommandHandler("undervalued", commands["undervalued"]))

    app.add_handler(CommandHandler("congress", commands["congress"]))
    app.add_handler(CommandHandler("insiders", commands["insiders"]))
    app.add_handler(CommandHandler("sec", commands["sec"]))
    app.add_handler(CommandHandler("filing", commands["filing"]))