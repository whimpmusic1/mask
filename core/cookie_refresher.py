"""
Keeps the yt-dlp cookies.txt session alive between manual re-exports.

What this does and doesn't do (read this before relying on it):

- Google's session cookies use a *sliding* expiry - each real request made
  with them tends to renew how long they're good for. Normal bot usage
  already does this a little (yt-dlp loads the cookie jar, uses it, and
  saves back whatever the server renewed), but if the bot goes quiet for a
  while (no one plays anything), the session can go stale from pure
  inactivity before yt-dlp ever gets to touch it.
- This background task just periodically makes one lightweight, real
  request to youtube.com with the existing cookies, so the session stays
  "used" even during idle periods, and re-saves the jar afterwards.
- It CANNOT recover from a session that's been outright revoked - e.g. you
  signed out elsewhere, Google flagged the account, or changed the
  password. There is no automatable, ToS-safe way to script past that; at
  that point a human has to re-export cookies.txt from a real browser
  again (see README). This script only delays how often that's needed,
  it doesn't eliminate it.
"""

import asyncio
import http.cookiejar
import logging
import urllib.request

from config import Config

logger = logging.getLogger(__name__)

_TOUCH_URL = "https://www.youtube.com/"
_REFRESH_EVERY_SECONDS = 6 * 60 * 60  # every 6 hours
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _touch_sync() -> bool:
    path = Config.YTDLP_COOKIES_FILE
    if not path:
        return False

    jar = http.cookiejar.MozillaCookieJar(path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        logger.warning("No readable cookies file at %s yet - skipping touch.", path)
        return False

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", _USER_AGENT)]

    try:
        with opener.open(_TOUCH_URL, timeout=20) as resp:
            resp.read(2048)  # just enough to complete the exchange, not the whole page
    except Exception:
        logger.exception("Cookie keep-alive request failed")
        return False

    try:
        jar.save(ignore_discard=True, ignore_expires=True)
    except Exception:
        logger.exception("Touched YouTube but failed to re-save the cookies file")
        return False

    return True


async def _touch_once() -> None:
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, _touch_sync)
    if ok:
        logger.info("Cookie keep-alive touch OK - cookies file re-saved.")


async def run_forever() -> None:
    """Call this once as a background asyncio task from bot.py."""
    if not Config.YTDLP_COOKIES_FILE:
        logger.info("No cookies file configured - cookie refresher won't run.")
        return

    while True:
        try:
            await _touch_once()
        except Exception:
            # Never let a refresh hiccup take the whole bot down.
            logger.exception("Unexpected error in cookie refresher loop")
        await asyncio.sleep(_REFRESH_EVERY_SECONDS)
