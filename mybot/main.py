import os, re, requests, yt_dlp, threading, asyncio, tempfile
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot is Running!"
def run_web():
    web_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reel ka link bhejo!")

# Jab link aayega to option do
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "instagram.com" not in text: return
    m = re.search(r'https?://(?:www\.)?instagram\.com/\S+', text)
    if not m: return
    link = m.group(0)
    context.user_data['link'] = link

    keyboard = [
        [InlineKeyboardButton("⚡ SuperFast (480p ~5MB)", callback_data="480")],
        [InlineKeyboardButton("🚀 Fast (720p ~8MB)", callback_data="720")],
        [InlineKeyboardButton("💎 HD Quality (1080p ~30MB)", callback_data="1080")]
    ]
    await update.message.reply_text("Quality choose karo 👇", reply_markup=InlineKeyboardMarkup(keyboard))

# Progress animation ke liye
async def update_progress(message, percent):
    try:
        bar = "█" * int(percent/10) + "░" * (10-int(percent/10))
        await message.edit_text(f"Downloading...\n{bar} {percent:.2f}%\n⏳ Please wait...")
    except: pass # Flood control

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quality = query.data
    link = context.user_data.get('link')

    status_msg = await query.edit_message_text(f"Starting download {quality}p... 0.00%")

    # Ye function blocking hai, isliye dusre thread me chalayenge taaki 100 user handle ho sake
    def download_with_progress():
        tmp = tempfile.gettempdir()
        fpath = os.path.join(tmp, f"reel_{quality}.mp4")

        last_percent = 0
        def hook(d):
            nonlocal last_percent
            if d['status'] == 'downloading':
                p = d.get('_percent_str','0%').replace('%','')
                try: cur = float(p)
                except: cur = 0
                # Har 3% par hi animation update karo warna Telegram ban kar dega
                if cur - last_percent > 3:
                    last_percent = cur
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(update_progress(status_msg, cur))

        # Cobalt se quality ke hisab se mango
        try:
            r = requests.post("https://co.wuk.sh/api/json",
                json={"url": link.split("?")[0], "vQuality": quality, "vCodec": "h264"},
                headers={"Accept":"application/json"}, timeout=30)
            v_url = r.json().get("url")
            if v_url:
                # requests se % nikalna
                resp = requests.get(v_url, stream=True, timeout=60)
                total = int(resp.headers.get('content-length', 0))
                done = 0
                with open(fpath, 'wb') as f:
                    for chunk in resp.iter_content(1024*256):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            per = done/total*100
                            if per - last_percent > 2:
                                last_percent = per
                                loop = asyncio.new_event_loop()
                                loop.run_until_complete(update_progress(status_msg, per))
                return fpath
        except Exception as e:
            print(e)

        # Fallback yt-dlp
        try:
            ydl_opts = {'outtmpl': fpath, 'format': f'best[height<={quality}]', 'quiet': True, 'progress_hooks': [hook]}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([link])
            return fpath
        except: return None

    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, download_with_progress)

    if path and os.path.exists(path):
        await status_msg.edit_text("Uploading... 99%")
        await context.bot.send_video(chat_id=query.message.chat_id, video=open(path,'rb'), caption=f"Ye lo {quality}p ✅")
        await status_msg.delete()
        os.remove(path)
    else:
        await status_msg.edit_text("Fail ho gaya, private reel hai.")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    print("Bot chal raha hai...")
    # Important: 100 user ke liye concurrency badhao
    app = Application.builder().token(TOKEN).concurrent_updates(100).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_click))
    app.run_polling()

if __name__ == "__main__":
    main()            print(f"Cobalt error {api}: {e}")

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
