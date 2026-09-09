import os
from pathlib import Path
import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Token environment variable se lena hai
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 InstaReel Downloader Bot me Swagat hai! 🔥\n\n"
        "Bas Instagram Reel ka link bhejo, mai turant download karke bhej dunga! 🚀\n\n"
        "Note: Sirf apne ya public reels ke liye use karo."
    )

def download_reel(url: str):
    download_dir = Path("downloads")
    download_dir.mkdir(exist_ok=True)
    url = url.split("?")[0].strip()
    ydl_opts = {
        'outtmpl': str(download_dir / '%(title)s.%(ext)s'),
        'format': 'bestvideo+bestaudio/best',
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename, info.get('title', 'Insta Reel')

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "instagram.com" not in text:
        await update.message.reply_text("❌ Ye Instagram ka link nahi hai!")
        return
    status_msg = await update.message.reply_text("📥 Download ho raha hai...")
    try:
        filepath, title = download_reel(text)
        await status_msg.edit_text("📤 Bhej raha hoon...")
        with open(filepath, 'rb') as video:
            await update.message.reply_video(video=video, caption=f"✅ {title}")
        await status_msg.delete()
        os.remove(filepath)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.run_polling()

if __name__ == "__main__":
    main()
