import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import tempfile

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bhejo Instagram Reel ka link, mai download karke deta hu! 🔥")

async def download_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if "instagram.com" not in url and "instagr.am" not in url:
        await update.message.reply_text("Ye Instagram link nahi lag raha 🤔")
        return

    await update.message.reply_text("Downloading... ⏳")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'outtmpl': f'{tmpdir}/%(title)s.%(ext)s',
                'format': 'best',
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)

            await update.message.reply_video(video=open(filename, 'rb'), caption="Lo ho gaya ✅ @alok ke bot se")
    except Exception as e:
        logging.error(e)
        await update.message.reply_text(f"Error aa gaya: {e}")

def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN nahi mila!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_reel))
    print("Bot chal raha hai...")
    app.run_polling()

if name == "main":
    main()
