#!/usr/bin/env python3
# bot.py

import os, logging
from flask import Flask, request
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram import ParseMode
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, CallbackContext

from hianimez_scraper import (
    search_anime,
    get_episodes_list,
    extract_episode_stream_and_subtitle
)
from utils import download_and_rename_subtitle

# -------------------------
# Env & logging
# -------------------------
from dotenv import load_dotenv
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")

KOYEB_APP_URL = os.getenv("KOYEB_APP_URL")  # e.g., https://yourapp.koyeb.app
if not KOYEB_APP_URL:
    raise RuntimeError("KOYEB_APP_URL is not set (public https URL needed for webhook)")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("hianime-bot")

# -------------------------
# Flask + Telegram setup
# -------------------------
app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)  # PTB v13.x style

# -------------------------
# Handlers
# -------------------------
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Hi! Use /search <name>\n"
        "I’ll find your anime on your HiAnime domains and, for any episode you pick,\n"
        "return the **SUB: HD‑2** highest-quality stream + **English** subtitle.",
        parse_mode=ParseMode.HTML
    )

def search_command(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /search <anime name>")
        return

    query = " ".join(context.args).strip()
    msg = update.message.reply_text(f"🔍 Searching for \"{query}\"…")
    try:
        results = search_anime(query)
    except Exception as e:
        logger.exception("Search error")
        msg.edit_text("❌ Error during search; please try again.")
        return

    if not results:
        msg.edit_text(f"No anime found for \"{query}\".")
        return

    buttons = [[InlineKeyboardButton(title, callback_data=f"anime|{anime_url}")]
               for (title, anime_url, _) in results]
    msg.edit_text("Select the anime:", reply_markup=InlineKeyboardMarkup(buttons))

def anime_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    try:
        _, anime_url = query.data.split("|", 1)
    except ValueError:
        query.edit_message_text("Invalid selection.")
        return

    query.edit_message_text("📺 Loading episodes…")
    try:
        episodes = get_episodes_list(anime_url)
    except Exception:
        logger.exception("Episode list fetch error")
        query.edit_message_text("❌ Failed to retrieve episodes.")
        return

    if not episodes:
        query.edit_message_text("No episodes found.")
        return

    # Build episode buttons (chunk to avoid exceeding Telegram button limits)
    rows = []
    for ep_num, ep_url in episodes:
        label = f"Ep {ep_num}"
        rows.append([InlineKeyboardButton(label, callback_data=f"ep|{ep_num}|{ep_url}")])

    query.edit_message_text("Choose an episode:", reply_markup=InlineKeyboardMarkup(rows))

def episode_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    try:
        _, ep_num, ep_url = query.data.split("|", 2)
    except ValueError:
        query.edit_message_text("Invalid episode selection.")
        return

    query.edit_message_text(f"🔄 Getting SUB: HD‑2 + English subtitle for Episode {ep_num}…")

    try:
        hls_link, subtitle_url = extract_episode_stream_and_subtitle(ep_url)
    except Exception:
        logger.exception("Extract error")
        query.edit_message_text(f"❌ Failed to extract data for Episode {ep_num}.")
        return

    if not hls_link:
        query.edit_message_text("😔 No SUB: HD‑2 stream found for this episode.")
        return

    text = (
        f"🎬 *Episode {ep_num}*\n\n"
        f"🔗 *SUB: HD‑2 (highest HLS)*:\n`{hls_link}`\n\n"
    )

    if not subtitle_url:
        text += "📝 English subtitle: *not found*"
        query.edit_message_text(text, parse_mode=ParseMode.HTML)
        return

    # Download and send the English subtitle as file
    try:
        local_vtt = download_and_rename_subtitle(subtitle_url, ep_num, cache_dir="subtitles_cache")
    except Exception:
        logger.exception("Subtitle download error")
        text += "⚠️ Found English subtitle URL but failed to download."
        query.edit_message_text(text, parse_mode=ParseMode.HTML)
        return

    text += f"✅ English subtitle saved as `Episode {ep_num}.vtt`."
    query.edit_message_text(text, parse_mode=ParseMode.HTML)

    with open(local_vtt, "rb") as f:
        query.message.reply_document(
            document=InputFile(f, filename=f"Episode {ep_num}.vtt"),
            caption=f"Here is the subtitle for Episode {ep_num}."
        )

    try:
        os.remove(local_vtt)
    except OSError:
        pass

# Register handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("search", search_command))
dispatcher.add_handler(CallbackQueryHandler(anime_callback, pattern=r"^anime\|"))
dispatcher.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^ep\|"))

# -------------------------
# Flask endpoints
# -------------------------
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok", 200

# -------------------------
# Boot: set webhook
# -------------------------
if __name__ == "__main__":
    webhook_url = f"{KOYEB_APP_URL}/webhook"
    try:
        bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    except Exception as ex:
        logger.exception("Failed to set webhook")
        raise

    os.makedirs("subtitles_cache", exist_ok=True)
    PORT = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting Flask on :{PORT}")
    app.run(host="0.0.0.0", port=PORT)
