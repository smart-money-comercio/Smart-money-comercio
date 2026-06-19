from datetime import datetime

def build_daily_report():
    today = datetime.now().strftime("%B %d, %Y")

    report = f"""
🚀 SMART MONEY AI
Daily Report - {today}

🔥 TOP PICKS
1. PLTR - Score: 93
2. AVAV - Score: 91
3. NVDA - Score: 90

🛡️ DEFENSE INTELLIGENCE
1. AVAV - Drone Warfare / Counter-Drone
2. KTOS - Autonomous Aircraft
3. PLTR - AI Warfare
4. CRWD - Cyber Warfare
5. LMT - Defense Prime

📊 PORTFOLIO STRATEGY
Growth: 40%
Defense / AI Warfare: 20%
ETFs: 25%
Dividend: 15%

🧠 AI SUMMARY
Defense, AI, cybersecurity, and autonomous systems remain priority themes for monitoring.

Status: MVP test report
"""
    return report.strip()