import asyncio
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

import requests
import yt_dlp
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
MAX_CONCURRENT_DOWNLOADS = max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "4")))
MAX_SEND_BYTES = int(os.getenv("MAX_SEND_BYTES", str(49 * 1024 * 1024)))
REQUEST_TTL_SECONDS = 30 * 60

COBALT_ENDPOINTS = (
    "https://co.wuk.sh/api/json",
    "https://api.cobalt.tools/api/json",
)

QUALITY_CONFIG = {
    "480": {"label": "⚡ SuperFast 480p", "height": 480, "target_mb": 5.0},
    "720": {"label": "🚀 Fast 720p", "height": 720, "target_mb": 8.0},
    "1080": {"label": "💎 HD 1080p", "height": 1080, "target_mb": None},
}

INSTAGRAM_URL_RE = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?(?:instagram\.com|instagr\.am)/[^\s<>\"']+",
    re.IGNORECASE,
)
INSTAGRAM_PATH_RE = re.compile(
    r"/(?:reel|reels|p|tv)/([A-Za-z0-9_-]{5,})", re.IGNORECASE
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("reel-bot")

web_app = Flask(__name__)
download_slots: Optional[asyncio.Semaphore] = None


# -----------------------------------------------------------------------------
# Render health server
# -----------------------------------------------------------------------------
@web_app.get("/")
def home():
    return {"status": "ok", "service": "instagram-reel-bot"}, 200


@web_app.get("/health")
def health():
    return "OK", 200


def run_web() -> None:
    # Render supplies PORT. The Flask development server is sufficient for these
    # lightweight health endpoints; Telegram polling remains in the main thread.
    web_app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True,
        use_reloader=False,
    )


# -----------------------------------------------------------------------------
# URL handling
# -----------------------------------------------------------------------------
def clean_instagram_url(raw_url: str) -> str:
    """Return a canonical URL containing only /reel/<shortcode>/."""
    candidate = raw_url.strip().replace("&amp;", "&")
    candidate = candidate.rstrip(".,;:!?)]}'\"")
    parsed = urlparse(candidate)

    host = (parsed.hostname or "").lower()
    if host != "instagram.com" and not host.endswith(".instagram.com") and host != "instagr.am":
        raise ValueError("Not an Instagram URL")

    path = unquote(parsed.path)
    match = INSTAGRAM_PATH_RE.search(path)
    if not match:
        raise ValueError("Reel shortcode not found in the URL")

    shortcode = match.group(1)
    return f"https://www.instagram.com/reel/{shortcode}/"


def extract_instagram_url(text: str) -> Optional[str]:
    match = INSTAGRAM_URL_RE.search(text or "")
    if not match:
        return None
    return clean_instagram_url(match.group(0))


# -----------------------------------------------------------------------------
# Download helpers (all blocking work runs in a worker thread)
# -----------------------------------------------------------------------------
ProgressCallback = Callable[[str, float], None]


def _safe_progress(callback: ProgressCallback, stage: str, percent: float) -> None:
    try:
        callback(stage, max(0.0, min(100.0, float(percent))))
    except Exception:
        # Progress reporting must never break a download.
        pass


def _download_stream(
    session: requests.Session,
    media_url: str,
    output_path: Path,
    progress: ProgressCallback,
    stage: str,
) -> Path:
    headers = {
        "Accept": "video/*,application/octet-stream;q=0.9,*/*;q=0.8",
        "Referer": "https://www.instagram.com/",
    }
    with session.get(
        media_url,
        headers=headers,
        stream=True,
        allow_redirects=True,
        timeout=(15, 180),
    ) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            preview = response.content[:300].decode("utf-8", errors="replace")
            raise RuntimeError(f"Media endpoint returned {content_type}: {preview}")

        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with output_path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    _safe_progress(progress, stage, downloaded * 100.0 / total)

    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("Downloaded media is empty")
    _safe_progress(progress, stage, 100.0)
    return output_path


def _extract_cobalt_media_url(data: dict) -> Optional[str]:
    direct = data.get("url")
    if isinstance(direct, str) and direct.startswith("http"):
        return direct

    # Some Cobalt instances return a picker array instead of a direct URL.
    picker = data.get("picker")
    if isinstance(picker, list):
        video_candidates = []
        other_candidates = []
        for item in picker:
            if not isinstance(item, dict):
                continue
            item_url = item.get("url")
            if not isinstance(item_url, str) or not item_url.startswith("http"):
                continue
            if item.get("type") == "video":
                video_candidates.append(item_url)
            else:
                other_candidates.append(item_url)
        if video_candidates:
            return video_candidates[0]
        if other_candidates:
            return other_candidates[0]
    return None


def _try_cobalt(
    endpoint: str,
    clean_url: str,
    quality: str,
    work_dir: Path,
    progress: ProgressCallback,
    attempt_number: int,
) -> Path:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; ReelDownloaderBot/1.0)",
        }
    )
    payload = {"url": clean_url, "vQuality": quality}
    logger.info("Trying Cobalt endpoint=%s quality=%s", endpoint, quality)

    response = session.post(endpoint, json=payload, timeout=(15, 45))
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Cobalt returned non-JSON: {response.text[:300]}") from exc

    media_url = _extract_cobalt_media_url(data)
    if not media_url:
        error_text = data.get("text") or data.get("error") or data.get("status") or str(data)[:300]
        raise RuntimeError(f"Cobalt did not return a video URL: {error_text}")

    output_path = work_dir / f"cobalt-{attempt_number}.mp4"
    return _download_stream(
        session,
        media_url,
        output_path,
        progress,
        stage=f"cobalt-{attempt_number}",
    )


def _try_ytdlp(
    clean_url: str,
    height: int,
    work_dir: Path,
    progress: ProgressCallback,
) -> Path:
    logger.info("Trying yt-dlp height<=%s url=%s", height, clean_url)
    output_template = str(work_dir / "ytdlp.%(ext)s")

    def hook(event: dict) -> None:
        if event.get("status") == "downloading":
            downloaded = event.get("downloaded_bytes") or 0
            total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
            if total:
                _safe_progress(progress, "yt-dlp", downloaded * 100.0 / total)
        elif event.get("status") == "finished":
            _safe_progress(progress, "yt-dlp", 100.0)

    # Prefer a single MP4 stream. The second choice follows the requested
    # best[height<=quality] fallback and avoids requiring ffmpeg for merging.
    format_selector = (
        f"best[ext=mp4][height<={height}]/"
        f"best[height<={height}]/best[ext=mp4]/best"
    )
    options = {
        "outtmpl": output_template,
        "format": format_selector,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 30,
        "progress_hooks": [hook],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
        },
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([clean_url])

    candidates = sorted(work_dir.glob("ytdlp.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidates or candidates[0].stat().st_size < 1024:
        raise RuntimeError("yt-dlp completed without a usable output file")
    return candidates[0]


def _find_ffmpeg() -> Optional[str]:
    configured = os.getenv("FFMPEG_BINARY", "").strip()
    if configured:
        return configured
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg  # Optional but recommended on Render.

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _probe_duration(ffmpeg: str, input_path: Path) -> Optional[float]:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(input_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _compress_to_target(
    input_path: Path,
    height: int,
    target_mb: Optional[float],
    work_dir: Path,
) -> Path:
    """Compress oversized 480p/720p files near the requested size when ffmpeg exists."""
    if target_mb is None:
        return input_path

    target_bytes = int(target_mb * 1024 * 1024)
    if input_path.stat().st_size <= int(target_bytes * 1.05):
        return input_path

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        logger.warning(
            "File is %.2f MB; ffmpeg is unavailable, so the %.1f MB target cannot be enforced",
            input_path.stat().st_size / 1024 / 1024,
            target_mb,
        )
        return input_path

    duration = _probe_duration(ffmpeg, input_path)
    if not duration or duration <= 0:
        logger.warning("Could not determine duration; skipping target-size compression")
        return input_path

    # Reserve about 6%% for the MP4 container and bitrate variance.
    total_kbps = (target_bytes * 8 / duration / 1000) * 0.94
    audio_kbps = 96 if total_kbps >= 500 else 64
    video_kbps = max(180, int(total_kbps - audio_kbps))
    output_path = work_dir / f"compressed-{height}p.mp4"
    passlog = str(work_dir / "ffmpeg-pass")
    scale = f"scale=-2:'min({height},ih)'"

    logger.info(
        "Compressing %.2f MB to about %.1f MB at %sp (video=%sk audio=%sk)",
        input_path.stat().st_size / 1024 / 1024,
        target_mb,
        height,
        video_kbps,
        audio_kbps,
    )

    common = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{video_kbps}k",
        "-bufsize",
        f"{video_kbps * 2}k",
        "-pix_fmt",
        "yuv420p",
    ]
    null_output = "NUL" if os.name == "nt" else "/dev/null"
    subprocess.run(
        common
        + ["-pass", "1", "-passlogfile", passlog, "-an", "-f", "mp4", null_output],
        check=True,
        timeout=900,
    )
    subprocess.run(
        common
        + [
            "-pass",
            "2",
            "-passlogfile",
            passlog,
            "-c:a",
            "aac",
            "-b:a",
            f"{audio_kbps}k",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        check=True,
        timeout=900,
    )

    if output_path.exists() and output_path.stat().st_size > 1024:
        return output_path
    raise RuntimeError("ffmpeg did not create a valid compressed file")


def download_reel(
    clean_url: str,
    quality: str,
    work_dir: Path,
    progress: ProgressCallback,
) -> Path:
    errors = []
    for index, endpoint in enumerate(COBALT_ENDPOINTS, start=1):
        try:
            path = _try_cobalt(endpoint, clean_url, quality, work_dir, progress, index)
            logger.info("Cobalt download succeeded endpoint=%s file=%s", endpoint, path)
            return _compress_to_target(
                path,
                QUALITY_CONFIG[quality]["height"],
                QUALITY_CONFIG[quality]["target_mb"],
                work_dir,
            )
        except Exception as exc:
            logger.exception("Cobalt failed endpoint=%s: %s", endpoint, exc)
            errors.append(f"{endpoint}: {exc}")

    try:
        path = _try_ytdlp(
            clean_url,
            QUALITY_CONFIG[quality]["height"],
            work_dir,
            progress,
        )
        logger.info("yt-dlp download succeeded file=%s", path)
        return _compress_to_target(
            path,
            QUALITY_CONFIG[quality]["height"],
            QUALITY_CONFIG[quality]["target_mb"],
            work_dir,
        )
    except Exception as exc:
        logger.exception("yt-dlp failed: %s", exc)
        errors.append(f"yt-dlp: {exc}")

    raise RuntimeError("All download methods failed | " + " | ".join(errors))


# -----------------------------------------------------------------------------
# Telegram progress and handlers
# -----------------------------------------------------------------------------
def progress_bar(percent: float, width: int = 10) -> str:
    filled = min(width, max(0, int(percent * width / 100)))
    return "█" * filled + "░" * (width - filled)


async def render_progress(message, events: queue.Queue, stop: asyncio.Event) -> None:
    last_stage = ""
    last_percent = -5.0
    last_edit = 0.0

    while not stop.is_set() or not events.empty():
        latest = None
        try:
            while True:
                latest = events.get_nowait()
        except queue.Empty:
            pass

        if latest is not None:
            stage, percent = latest
            now = time.monotonic()
            stage_changed = stage != last_stage
            enough_progress = percent >= last_percent + 4.0 or percent >= 99.9
            enough_time = now - last_edit >= 1.5

            if stage_changed:
                last_stage = stage
                last_percent = -5.0
                enough_progress = True

            if enough_progress and enough_time:
                text = f"Downloading... {progress_bar(percent)} {percent:.2f}%"
                try:
                    await message.edit_text(text)
                    last_percent = percent
                    last_edit = time.monotonic()
                except RetryAfter as exc:
                    await asyncio.sleep(float(exc.retry_after) + 0.2)
                except BadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        logger.warning("Progress edit rejected: %s", exc)
                except TelegramError as exc:
                    logger.warning("Progress edit failed: %s", exc)

        await asyncio.sleep(0.5)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Instagram Reel link bhejo!")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        clean_url = extract_instagram_url(update.message.text or "")
    except ValueError as exc:
        await update.message.reply_text(f"Valid Instagram Reel link nahi mila: {exc}")
        return

    if not clean_url:
        return

    request_id = uuid.uuid4().hex[:12]
    now = time.time()
    requests_map = context.user_data.setdefault("reel_requests", {})
    # Remove stale buttons/URLs from this user's in-memory state.
    for key, item in list(requests_map.items()):
        if now - item.get("created", 0) > REQUEST_TTL_SECONDS:
            requests_map.pop(key, None)
    requests_map[request_id] = {"url": clean_url, "created": now, "busy": False}

    keyboard = [
        [InlineKeyboardButton("⚡ SuperFast 480p ~5MB", callback_data=f"reel:{request_id}:480")],
        [InlineKeyboardButton("🚀 Fast 720p ~8MB", callback_data=f"reel:{request_id}:720")],
        [InlineKeyboardButton("💎 HD 1080p", callback_data=f"reel:{request_id}:1080")],
    ]
    await update.message.reply_text(
        "Quality select karo 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()

    match = re.fullmatch(r"reel:([a-f0-9]{12}):(480|720|1080)", query.data or "")
    if not match:
        await query.edit_message_text("Invalid button. Reel link dobara bhejo.")
        return

    request_id, quality = match.groups()
    requests_map = context.user_data.get("reel_requests", {})
    request_data = requests_map.get(request_id)
    if not request_data or time.time() - request_data.get("created", 0) > REQUEST_TTL_SECONDS:
        await query.edit_message_text("This button expired. Reel link dobara bhejo.")
        return
    if request_data.get("busy"):
        await query.answer("Download already running", show_alert=True)
        return

    request_data["busy"] = True
    clean_url = request_data["url"]
    status_message = query.message
    await status_message.edit_text("Waiting for a download slot... ⏳")

    work_dir = Path(tempfile.mkdtemp(prefix=f"reel-{request_id}-"))
    progress_events: queue.Queue = queue.Queue()
    stop_progress = asyncio.Event()
    progress_task = None

    def report_progress(stage: str, percent: float) -> None:
        progress_events.put((stage, percent))

    try:
        if download_slots is None:
            raise RuntimeError("Download queue is not initialized")

        async with download_slots:
            await status_message.edit_text("Downloading... ░░░░░░░░░░ 0.00%")
            progress_task = asyncio.create_task(
                render_progress(status_message, progress_events, stop_progress)
            )
            path = await asyncio.to_thread(
                download_reel,
                clean_url,
                quality,
                work_dir,
                report_progress,
            )

            stop_progress.set()
            await progress_task
            progress_task = None

            if not path.exists():
                raise RuntimeError("Output file disappeared before upload")

            size_bytes = path.stat().st_size
            size_mb = size_bytes / 1024 / 1024
            if size_bytes > MAX_SEND_BYTES:
                raise RuntimeError(
                    f"File is {size_mb:.1f} MB, above configured Telegram limit "
                    f"of {MAX_SEND_BYTES / 1024 / 1024:.1f} MB"
                )

            await status_message.edit_text(f"Uploading... {size_mb:.1f} MB ⏫")
            config = QUALITY_CONFIG[quality]
            with path.open("rb") as video_file:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=video_file,
                    caption=f"{config['label']} | {size_mb:.1f} MB ✅",
                    supports_streaming=True,
                    read_timeout=180,
                    write_timeout=180,
                    connect_timeout=30,
                    pool_timeout=30,
                )
            try:
                await status_message.delete()
            except TelegramError:
                pass
            requests_map.pop(request_id, None)

    except Exception as exc:
        logger.exception(
            "Request failed user=%s quality=%s url=%s: %s",
            update.effective_user.id if update.effective_user else "unknown",
            quality,
            clean_url,
            exc,
        )
        stop_progress.set()
        if progress_task:
            await progress_task
        request_data["busy"] = False
        try:
            await status_message.edit_text(
                "Download fail ho gaya. Reel private/expired ho sakti hai, ya source temporarily blocked hai. "
                "Thodi der baad dobara try karo."
            )
        except TelegramError:
            pass
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram update error", exc_info=context.error)


async def post_init(application: Application) -> None:
    global download_slots
    download_slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    bot = await application.bot.get_me()
    logger.info(
        "Bot started as @%s; max concurrent downloads=%s",
        bot.username,
        MAX_CONCURRENT_DOWNLOADS,
    )


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is missing")

    threading.Thread(target=run_web, name="render-health-server", daemon=True).start()

    application = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(100)
        .connection_pool_size(100)
        .pool_timeout(30)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)
    )
    application.add_handler(
        CallbackQueryHandler(button_click, pattern=r"^reel:[a-f0-9]{12}:(480|720|1080)$")
    )
    application.add_error_handler(error_handler)

    logger.info("Starting Telegram polling and Render health server on port %s", PORT)
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
