from telegram import Update
from telegram.ext import ContextTypes


VERSION_NOTES_TEXT = """
🚀 Smart Money AI v1.1
Adaptive Daily Brief

What’s New
• /brief — cleaner daily market brief
• What Changed Today — market-memory comparison
• Theme Read — stronger/fading/actionable themes
• AI Summary — Signal / Implication / Validation
• Top Opportunities — edge, trigger, risk/action
• Risk Notes — shorter decision-focused risk layer
• Action Checklist — next best commands
• /quality — report guardrail check
• /commands — cleaned product menu
• /help — quick-start guide
• Friendly aliases: /stock, /watch, /macro, /calendar

Report Intelligence
• Remembers recent market themes
• Tracks theme persistence and leadership shifts
• Reduces repeated headline noise
• Keeps /brief concise with quality guardrails

Best Daily Flow
1. /brief
2. /quality
3. /stock SYMBOL
4. /scorecard SYMBOL
5. /calendar

Research only. Not financial advice.
""".strip()


async def versionnotes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(VERSION_NOTES_TEXT)