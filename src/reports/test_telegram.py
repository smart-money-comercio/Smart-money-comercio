import os

print("current folder:", os.getcwd())

print("Script started")

import os
import requests
from dotenv import load_dotenv

load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print("Bot Token Found:", bool(bot_token))
print("Chat ID:", chat_id)

message = "🚀 Smart Money AI Online"

url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

response = requests.post(
    url,
    json={
        "chat_id": chat_id,
        "text": message
    }
)

print(response.status_code)
print(response.text)