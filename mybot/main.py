import os, re, requests, yt_dlp, threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Ye chota sa web server hai taaki Render ko lage bot zinda hai
web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Bot is Running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bhejo Instagram Reel ka link!")

def get_video_url(insta_link):
    clean_link = insta_link.split("?")[0]
    try:
        r = requests.post("https://co.wuk.sh/api/json", json={"url": clean_link}, headers={"Accept": "application/json"}, timeout=30)
        data = r.json()
        if data.get("url"):
            return data["url"]
    except:
        pass
    try:
        dd_link = clean_link.replace("instagram.com", "ddinstagram.com").replace("www.ddinstagram.com", "ddinstagram.com")
        with yt_dlp.YoutubeDL({'quiet': True, 'format': 'best'}) as ydl:
            info = ydl.extract_info(dd_link, download=False)
            return info.get('url')
    except:
        return None

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "instagram.com" not in text:
        return
    m = re.search(r'https?://(?:www\.)?instagram\.com/\S+', text)
    if not m:
        return
    link = m.group(0)
    await update.message.reply_text("Downloading... ⏳")
    vurl = get_video_url(link)
    if vurl:
        try:
            await update.message.reply_video(video=vurl)
        except:
            await update.message.reply_text(vurl)
    else:
        await update.message.reply_text("Download fail ho gaya.")

def main():
    # Web server ko background me chalao
    threading.Thread(target=run_web, daemon=True).start()
    print("Bot chal raha hai...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.run_polling()

if __name__ == "__main__":
    main()
