import base64
import logging
import os
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.sample to .env and fill it in."
        )
    return value


def _write_cookies_file() -> str | None:
    """
    Resolve the path to a yt-dlp cookies.txt file.

    Important: the env var is only a *seed*, used the first time there is
    no file on disk yet. If a cookies file already exists at this path
    (because it survived a restart, or because YTDLP_COOKIES_PATH points
    at a persistent Railway Volume), we leave it alone - yt-dlp rewrites
    that file with any renewed cookies after every run, and overwriting
    it from the (possibly stale) env var on every boot would throw that
    accumulated refresh away for no reason.
    """
    path = os.environ.get("YTDLP_COOKIES_PATH", "/app/cookies.txt")

    if os.path.exists(path):
        log.info("Using existing yt-dlp cookies file at %s (not reseeding).", path)
        return path

    b64 = (
    os.environ.get("YTDLP_COOKIES_B64_1", "")
    + os.environ.get("YTDLP_COOKIES_B64_2", "")
)
    if not b64:
        return None

    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        log.info("yt-dlp cookies file seeded at %s from YTDLP_COOKIES_B64.", path)
        return path
    except Exception:
        log.exception("Failed to decode YTDLP_COOKIES_B64 into a cookies file")
        return None


class Config:
    API_ID = int(_require("API_ID"))
    API_HASH = _require("API_HASH")
    BOT_TOKEN = _require("BOT_TOKEN")
    SESSION_STRING = _require("SESSION_STRING")

    OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
    # Safety cap so nobody accidentally streams a 4-hour video forever.
    DURATION_LIMIT_MIN = int(os.environ.get("DURATION_LIMIT_MIN", "60"))
    # Default video quality piped into the voice chat.
    VIDEO_QUALITY = os.environ.get("VIDEO_QUALITY", "SD_480p")

    # Path to a yt-dlp cookies.txt file, or None if YTDLP_COOKIES_B64 isn't set.
    YTDLP_COOKIES_FILE = _write_cookies_file()
