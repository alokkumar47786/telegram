import os, re, requests, threading, tempfile, asyncio
import yt_dlp
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

web_app = Flask(__name__)
@web_app.route('/')
def home():
    return "Bot is Running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reel ka link bhejo!")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "instagram.com" not in text:
        return
    m = re.search(r'https?://(?:www\.)?instagram\.com/\S+', text)
    if not m:
        return
    link = m.group(0)
    context.user_data['link'] = link
    keyboard = [
        [InlineKeyboardButton("⚡ SuperFast 480p", callback_data="480")],
        [InlineKeyboardButton("🚀 Fast 720p", callback_data="720")],
        [InlineKeyboardButton("💎 HD 1080p", callback_data="1080")]
    ]
    await update.message.reply_text("Quality choose karo 👇", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quality = query.data
    link = context.user_data.get('link')
    if not link:
        await query.edit_message_text("Link expire ho gaya, dobara bhejo")
        return

    status_msg = await query.edit_message_text(f"Downloading {quality}p... 0%")

    def do_download(q, prog_cb):
        tmp = tempfile.gettempdir()
        fpath = os.path.join(tmp, f"reel_{q}.mp4")
        # Try Cobalt
        try:
            resp = requests.post(
                "https://co.wuk.sh/api/json",
                json={"url": link.split("?")[0], "vQuality": q, "vCodec": "h264"},
                headers={"Accept": "application/json"},
                timeout=40
            )
            data = resp.json()
            v_url = data.get("url")
            if v_url:
                r = requests.get(v_url, stream=True, timeout=60)
                total = int(r.headers.get("content-length", 0))
                done = 0
                last = 0
                with open(fpath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=256*1024):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if total > 0:
                                per = int(done/total*100)
                                if per - last >= 5:
                                    last = per
                                    prog_cb(per)
                return fpath
        except Exception as e:
            print("Cobalt fail", e)

        # Fallback yt-dlp
        try:
            def hook(d):
                if d['status'] == 'downloading':
                    s = d.get('_percent_str', '0%').replace('%','').strip()
                    try:
                        per = int(float(s))
                        prog_cb(per)
                    except:
                        pass
            opts = {'outtmpl': fpath, 'format': f'best[height<={q}]', 'quiet': True, 'progress_hooks': [hook]}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([link])
            return fpath
        except Exception as e:
            print("yt-dlp fail", e)
            return None

    last_percent = 0
    def progress_callback(p):
        nonlocal last_percent
        if p - last_percent >= 3:
            last_percent = p
            bar = "█" * int(p/10) + "░" * (10 - int(p/10))
            try:
                asyncio.run_coroutine_threadsafe(
                    status_msg.edit_text(f"Downloading...\n{bar} {p}%\nQuality: {quality}p"),
                    asyncio.get_event_loop()
                )
            except:
                pass

    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, do_download, quality, progress_callback)

    if path and os.path.exists(path):
        try:
            await status_msg.edit_text("Uploading... 95%")
            await context.bot.send_video(chat_id=query.message.chat_id, video=open(path, 'rb'), caption=f"{quality}p ✅")
            await status_msg.delete()
            os.remove(path)
        except Exception as e:
            await status_msg.edit_text(f"Upload fail: {e}")
    else:
        await status_msg.edit_text("Fail ho gaya. Private reel hai ya Insta ne block kiya. Dusri public reel try karo.")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    print("Bot chal raha hai...")
    app = Application.builder().token(TOKEN).concurrent_updates(100).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_click))
    app.run_polling()

if __name__ == "__main__":
    main()
    
