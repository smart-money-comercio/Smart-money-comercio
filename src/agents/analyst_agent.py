import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

def generate_ai_summary(scores):
    top_stocks = scores[:5]

    stock_text = "\n".join(
        [
            f"""
Ticker: {stock['ticker']}
Category: {stock['category']}
Smart Money Score: {stock['smart_score']}
Defense Score: {stock['defense_score']}
Final Score: {stock['final_score']}
"""
            for stock in top_stocks
        ]
    )

    prompt = f"""
You are the AI Analyst Agent for Smart Money AI.

Smart Money AI tracks:
- Congressional trading activity
- Insider buying
- Defense technology
- Drone warfare
- Counter-drone systems
- AI warfare
- Cybersecurity
- Autonomous systems

Today's highest-ranked companies:

{stock_text}

Write a concise daily analyst summary.

Include:
1. Which company appears strongest today and why.
2. Which defense or AI theme looks most important.
3. One risk investors should monitor.
4. A reminder that this is research, not financial advice.

Maximum 150 words.
Use a professional but clear tone.
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    return response.output_text

def analyze_stock(stock):

    prompt = f"""
You are Smart Money AI.

Analyze this stock:

Ticker: {stock['ticker']}
Category: {stock['category']}
Smart Score: {stock['smart_score']}
Defense Score: {stock['defense_score']}
Final Score: {stock['final_score']}

Explain:
1. Why it is ranked this way.
2. Key strengths.
3. Key risks.
4. What investors should monitor.

Maximum 120 words.
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    return response.output_text