import os, re, requests, yt_dlp, threading, tempfile
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot is Running!"
def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reel ka link bhejo!")

def get_video_path(insta_link):
    clean = insta_link.split("?")[0]
    tmp = tempfile.gettempdir()
    out_path = os.path.join(tmp, "%(id)s.%(ext)s")

    # Try 1: Cobalt API download
    for api in ["https://co.wuk.sh/api/json", "https://api.cobalt.tools/api/json"]:
        try:
            print(f"Trying Cobalt {api}")
            r = requests.post(api, json={"url": clean}, headers={"Accept":"application/json"}, timeout=40)
            j = r.json()
            v_url = j.get("url")
            if v_url:
                # download video file
                vid = requests.get(v_url, stream=True, timeout=60)
                fpath = os.path.join(tmp, "reel.mp4")
                with open(fpath, 'wb') as f:
                    for chunk in vid.iter_content(1024*1024):
                        f.write(chunk)
                return fpath
        except Exception as e:
            print(f"Cobalt error {api}: {e}")

    # Try 2: yt-dlp direct (with mobile headers)
    try:
        print("Trying yt-dlp direct")
        ydl_opts = {'outtmpl': out_path, 'quiet': True, 'no_warnings': True, 'format': 'best'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        print(f"yt-dlp error: {e}")
        return None

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "instagram.com" not in text:
        return
    m = re.search(r'https?://(?:www\.)?instagram\.com/\S+', text)
    if not m: return
    link = m.group(0)
    await update.message.reply_text("Downloading... ⏳ 15 sec lagega")
    path = get_video_path(link)
    if path and os.path.exists(path):
        try:
            await update.message.reply_video(video=open(path, 'rb'), caption="Ye lo ✅")
            os.remove(path)
        except Exception as e:
            await update.message.reply_text(f"Video mila par send fail: {e}")
    else:
        await update.message.reply_text("Fail ho gaya. Ye reel private hai ya Instagram ne block kiya hai. Dusri public reel try karo.")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    print("Bot chal raha hai...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.run_polling()

if __name__ == "__main__":
    main()
