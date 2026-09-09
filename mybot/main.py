import os, re, requests, threading, tempfile
import yt_dlp
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot is Running!"
def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reel link bhejo!")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "instagram.com" not in text: return
    m = re.search(r'https?://(?:www\.)?instagram\.com/\S+', text)
    if not m: return
    context.user_data['link'] = m.group(0)
    keyboard = [
        [InlineKeyboardButton("⚡ SuperFast 480p ~5MB", callback_data="480")],
        [InlineKeyboardButton("🚀 Fast 720p ~8MB", callback_data="720")],
        [InlineKeyboardButton("💎 HD 1080p", callback_data="best")]
    ]
    await update.message.reply_text("Quality select karo 👇", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quality = query.data
    link = context.user_data.get('link')

    msg = await query.edit_message_text(f"Downloading {quality}p... ⏳")

    # DOWNLOAD FUNCTION - Simple, no animation thread issue
    def download():
        clean = link.split("?")[0]
        tmp = tempfile.gettempdir()
        out = os.path.join(tmp, "reel.mp4")
        if os.path.exists(out): os.remove(out)

        # 1. Pehle wala purana method jo kaam kar raha tha
        for api_url in ["https://co.wuk.sh/api/json", "https://api.cobalt.tools/api/json"]:
            try:
                print(f"Trying {api_url} quality {quality}")
                payload = {"url": clean}
                if quality!= "best":
                    payload["vQuality"] = quality

                r = requests.post(api_url, json=payload, headers={"Accept":"application/json"}, timeout=30)
                print(r.text[:200])
                v_url = r.json().get("url")
                if v_url:
                    print("Got video url, downloading file")
                    with requests.get(v_url, stream=True, timeout=60) as vid:
                        with open(out, 'wb') as f:
                            for chunk in vid.iter_content(1024*1024):
                                f.write(chunk)
                    return out
            except Exception as e:
                print(f"API {api_url} fail: {e}")
                continue

        # 2. Fallback yt-dlp
        try:
            print("Trying yt-dlp")
            fmt = f"best[height<={quality}]" if quality!= "best" else "best"
            ydl_opts = {"outtmpl": out, "format": fmt, "quiet": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([clean])
            return out
        except Exception as e:
            print(f"yt-dlp fail {e}")
            return None

    import asyncio
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, download)

    if path and os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024*1024)
        await msg.edit_text(f"Uploading... {size_mb:.1f}MB")
        try:
            await context.bot.send_video(chat_id=query.message.chat_id, video=open(path, 'rb'), caption=f"{quality}p | {size_mb:.1f}MB ✅")
            await msg.delete()
            os.remove(path)
        except Exception as e:
            await msg.edit_text(f"Send fail: {e}")
    else:
        await msg.edit_text("Fail ho gaya. Ek baar logs bhejo.")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    print("Bot chal raha hai...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_click))
    app.run_polling()

if __name__ == "__main__":
    main()
