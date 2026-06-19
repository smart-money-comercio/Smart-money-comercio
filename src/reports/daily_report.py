from datetime import datetime
from src.scoring.scoring_engine import get_stock_scores

def build_daily_report():
    today = datetime.now().strftime("%B %d, %Y")
    scores = get_stock_scores()

    top_picks = "\n".join(
        [f"{i+1}. {s['ticker']} - Score: {s['final_score']} ({s['category']})"
         for i, s in enumerate(scores[:5])]
    )

    defense_picks = "\n".join(
        [f"{i+1}. {s['ticker']} - Defense Score: {s['defense_score']} ({s['category']})"
         for i, s in enumerate(sorted(scores, key=lambda x: x["defense_score"], reverse=True)[:5])]
    )

    report = f"""
🚀 SMART MONEY AI
Daily Report - {today}

🔥 TOP PICKS
{top_picks}

🛡️ DEFENSE INTELLIGENCE
{defense_picks}

📊 PORTFOLIO STRATEGY
Growth: 40%
Defense / AI Warfare: 20%
ETFs: 25%
Dividend: 15%

🧠 AI SUMMARY
Defense, AI, cybersecurity, drones, and autonomous systems remain priority investment themes.

Status: MVP scoring engine active
"""
    return report.strip()