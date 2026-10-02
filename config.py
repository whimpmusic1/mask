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

    The Railway Base64 values are a seed. An existing cookies file is kept so
    yt-dlp's own cookie updates are not discarded on every restart. Delete the
    persisted file (or point YTDLP_COOKIES_PATH at a fresh location) when a
    newly exported cookie set needs to be seeded.
    """
    path = os.environ.get("YTDLP_COOKIES_PATH", "/app/cookies.txt")


    b64_1 = os.environ.get("YTDLP_COOKIES_B64_1", "")
    b64_2 = os.environ.get("YTDLP_COOKIES_B64_2", "")
    b64 = b64_1 + b64_2

    if not b64:
        b64 = os.environ.get("YTDLP_COOKIES_B64", "")

    if not b64:
        return None

    try:
        raw = base64.b64decode(b64, validate=True)
        if not raw.strip():
            raise ValueError("Decoded cookies file is empty")

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(path, "wb") as f:
            f.write(raw)

        log.info("yt-dlp cookies file seeded at %s (%d bytes).", path, len(raw))
        return path
    except Exception:
        log.exception("Failed to decode cookie environment variables into a cookies file")
        return None


class Config:
    API_ID = int(_require("API_ID"))
    API_HASH = _require("API_HASH")
    BOT_TOKEN = _require("BOT_TOKEN")
    SESSION_STRING = _require("SESSION_STRING")

    # Accept the current plural variable and the older singular variable.
    owner_values = ",".join(
        value
        for value in (
            os.environ.get("OWNER_IDS", "").strip(),
            os.environ.get("OWNER_ID", "").strip(),
        )
        if value
    )
    OWNER_IDS = tuple(
        dict.fromkeys(
            int(owner_id.strip())
            for owner_id in owner_values.split(",")
            if owner_id.strip()
        )
    )

    # First owner is used for the Owner button; every listed ID has owner permissions.
    OWNER_ID = OWNER_IDS[0] if OWNER_IDS else 0
    OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "").strip().lstrip("@")

    UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/psycho_dv")
    SUPPORT_URL = os.environ.get(
        "SUPPORT_URL", "https://t.me/+pra5-89rnZoxYzQ1"
    )

    DURATION_LIMIT_MIN = int(os.environ.get("DURATION_LIMIT_MIN", "60"))
    VIDEO_QUALITY = os.environ.get("VIDEO_QUALITY", "SD_480p")

    YTDLP_COOKIES_FILE = _write_cookies_file()
