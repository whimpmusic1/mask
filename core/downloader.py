import asyncio
import logging

import yt_dlp

from config import Config

logger = logging.getLogger(__name__)


_COMMON_OPTS = {
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "geo_bypass": True,
    "nocheckcertificate": True,
    "skip_download": True,

    # Use Node for YouTube JavaScript challenges (nsig decryption etc).
    # Requires Node.js to actually be installed in the image - see Dockerfile.
    "js_runtimes": {
        "node": {},
    },

    # Keep EJS available for current YouTube extraction.
    "remote_components": {
        "ejs": ["github"],
    },

    "extractor_args": {
        "youtube": {
            "player_client": ["default", "web_embedded"],
        },
    },

    # Retry transient YouTube failures.
    "retries": 3,
    "fragment_retries": 3,
}

# If YTDLP_COOKIES_B64 was set, config.py already decoded it to a file on
# disk - point yt-dlp at it so requests look like a real logged-in session.
# This is the reliable fix for YouTube's "Sign in to confirm you're not a
# bot" wall once player-client swapping alone stops working (see README).
if Config.YTDLP_COOKIES_FILE:
    _COMMON_OPTS["cookiefile"] = Config.YTDLP_COOKIES_FILE
else:
    logger.warning(
        "No YTDLP_COOKIES_B64 set - YouTube extraction may hit "
        "'Sign in to confirm you're not a bot' errors, especially from a "
        "datacenter IP like Railway's. See README for how to add cookies."
    )


_AUDIO_OPTS = {
    **_COMMON_OPTS,
    "format": "bestaudio/best",
}


_VIDEO_OPTS = {
    **_COMMON_OPTS,
    "format": "best[height<=480][ext=mp4]/best[height<=480]/best",
}


def _extract(query: str, video: bool) -> dict:
    opts = _VIDEO_OPTS if video else _AUDIO_OPTS

    logger.info("yt-dlp extracting: %s", query)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)

        if info.get("entries"):
            info = next(
                (
                    entry
                    for entry in info["entries"]
                    if entry
                ),
                None,
            )

        if not info:
            raise RuntimeError(
                "yt-dlp returned no result for the requested media."
            )

        return info


async def get_stream_info(query: str, video: bool = False) -> dict:
    loop = asyncio.get_running_loop()

    info = await loop.run_in_executor(
        None,
        _extract,
        query,
        video,
    )

    stream_url = info.get("url")

    if not stream_url and info.get("formats"):
        audio_formats = [
            fmt
            for fmt in info["formats"]
            if (
                fmt.get("url")
                and fmt.get("acodec") not in (None, "none")
            )
        ]

        if audio_formats:
            stream_url = audio_formats[-1]["url"]
        else:
            stream_url = info["formats"][-1].get("url")

    if not stream_url:
        raise RuntimeError(
            "yt-dlp could not resolve a playable stream."
        )

    return {
        "title": info.get("title") or query,
        "duration": info.get("duration") or 0,
        "url": stream_url,
        "webpage_url": info.get("webpage_url"),
        "thumbnail": info.get("thumbnail"),
    }
