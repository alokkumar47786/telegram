import os
import re
import requests
import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bhejo Instagram Reel ka link, mai download karke deta hu! 🔥")

def get_video_url(insta_link):
    clean_link = insta_link.split("?")[0]

    # METHOD 1: Cobalt API
    try:
        print("Trying Cobalt...")
        r = requests.post("https://co.wuk.sh/api/json",
            json={"url": clean_link},
            headers={"Accept": "application/json"},
            timeout=30
        )
        data = r.json()
        if data.get("url"):
            print("Cobalt Success")
            return data["url"]
    except Exception as e:
        print(f"Cobalt Fail: {e}")

    # METHOD 2: DDInstagram + yt-dlp (no login needed)
    try:
        print("Trying DD...")
        dd_link = clean_link.replace("instagram.com", "ddinstagram.com").replace("www.ddinstagram.com", "ddinstagram.com")
        ydl_opts = {'quiet': True, 'no_warnings': True, 'format': 'best'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(dd_link, download=False)
            return info.get('url')
    except Exception as e:
        print(f"DD Fail: {e}")
        return None

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "instagram.com" not in text:
        return

    match = re.search(r'https?://(?:www\.)?instagram\.com/\S+', text)
    if not match:
        return

    insta_link = match.group(0)
    await update.message.reply_text("Downloading... ⏳")

    video_url = get_video_url(insta_link)

    if video_url:
        try:
            await update.message.reply_video(video=video_url, caption="Ye lo! ✅")
        except:
            # agar video direct send na ho to link bhej do
            await update.message.reply_text(f"Direct link: {video_url}")
    else:
        await update.message.reply_text("Error: Ye reel download nahi ho payi. Private hogi ya link galat hai.")

def main():
    print("Bot chal raha hai...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.run_polling()

if __name__ == "__main__":
    main()        await update.message.reply_text(f"Error aa gaya: {e}")

def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN nahi mila!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_reel))
    print("Bot chal raha hai...")
    app.run_polling()

if __name__ == "__main__":
    main()
