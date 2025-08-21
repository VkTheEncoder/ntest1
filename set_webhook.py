# set_webhook.py
import os, sys
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()
TOKEN  = os.getenv("TELEGRAM_TOKEN")
APP_URL = os.getenv("APP_URL") or os.getenv("KOYEB_APP_URL")
if not TOKEN or not APP_URL:
    print("TELEGRAM_TOKEN and APP_URL/KOYEB_APP_URL must be set"); sys.exit(1)

url = APP_URL.rstrip("/") + "/webhook"
bot = Bot(TOKEN)
print("Setting webhook to:", url)
print(bot.set_webhook(url))
