import os
import requests
from dotenv import load_dotenv
from daily_report import build_daily_report

load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

report = build_daily_report()

url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

response = requests.post(
    url,
    json={
        "chat_id": chat_id,
        "text": report
    }
)

print(response.status_code)
print(response.text)