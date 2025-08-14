import os, re, asyncio, shutil, pathlib
import yt_dlp
from imageio_ffmpeg import get_ffmpeg_exe
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

ALLOWED_HOSTS = (
    "youtube.com", "youtu.be", "tiktok.com", "facebook.com", "fb.watch"
)

URL_REGEX = re.compile(r'(https?://[^\s]+)', re.IGNORECASE)

DOWNLOAD_DIR = pathlib.Path("/tmp/downloads")  # safe temp dir on most hosts
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

def extract_url(text: str) -> str | None:
    if not text:
        return None
    m = URL_REGEX.search(text.strip())
    if not m:
        return None
    url = m.group(1)
    return url

def supports_site(url: str) -> bool:
    return any(host in url.lower() for host in ALLOWED_HOSTS)

def ytdlp_download(url: str) -> tuple[str, dict]:
    """Run yt-dlp in a blocking thread, return (filepath, info_dict)."""
    ffmpeg_path = get_ffmpeg_exe()  # provides ffmpeg binary
    ydl_opts = {
        "outtmpl": str(DOWNLOAD_DIR / "%(title).80s.%(ext)s"),
        # Prefer a single progressive file; fall back to merge (needs ffmpeg)
        "format": "best[ext=mp4][protocol^=http]/best[protocol^=http]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": ffmpeg_path,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        # If merging happened, final file will be mp4
        if not os.path.exists(file_path):
            alt = pathlib.Path(file_path).with_suffix(".mp4")
            if alt.exists():
                file_path = str(alt)
    return file_path, info

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Welcome to AuraLinkerBot!\n"
        "Send me a TikTok, YouTube, or Facebook link and I’ll download it for you. 🌌"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Just paste a link from TikTok, YouTube, or Facebook.\n"
        "I’ll fetch the video and send it back.\n\n"
        "⚠️ Only download content you have rights to."
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    url = extract_url(text)
    if not url or not supports_site(url):
        await update.message.reply_text(
            "❌ Please send a valid TikTok, YouTube, or Facebook link."
        )
        return

    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    status = await update.message.reply_text("⏳ Downloading your video...")

    try:
        file_path, info = await asyncio.to_thread(ytdlp_download, url)
        title = info.get("title", "video")
        # Telegram can send big files, but if extremely large it may fail
        size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Try sending as a video; if it fails, we’ll try as a document
        try:
            with open(file_path, "rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption=f"✅ {title}\n🌌 Thanks for using AuraLinkerBot!"
                )
        except Exception:
            with open(file_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"✅ {title} (sent as file)\n🌌 Thanks for using AuraLinkerBot!"
                )

        await status.delete()
    except Exception as e:
        await status.edit_text(f"⚠️ Error: {e}")
    finally:
        # Clean up tmp folder if it gets large
        try:
            for p in DOWNLOAD_DIR.glob("*"):
                if p.is_file() and p.stat().st_mtime < (asyncio.get_event_loop().time() - 60*60):
                    p.unlink(missing_ok=True)
        except Exception:
            pass

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
