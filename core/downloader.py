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

    # Use Node for current YouTube JavaScript challenges.
    "js_runtimes": {"node": {}},
    "remote_components": {"ejs": ["github"]},

    "extractor_args": {
        "youtube": {
            # Keep the original mweb+PO-token path first; it is the path
            # used by the working deployment. We retry with alternate
            # clients only when YouTube returns an authentication/bot error.
            "player_client": ["mweb"],
        },
        "youtubepot-bgutilhttp": {
            "base_url": "http://127.0.0.1:4416",
        },
    },
    "retries": 3,
    "fragment_retries": 3,
}

if Config.YTDLP_COOKIES_FILE:
    _COMMON_OPTS["cookiefile"] = Config.YTDLP_COOKIES_FILE
    try:
        size = __import__("os").path.getsize(Config.YTDLP_COOKIES_FILE)
        logger.info("yt-dlp cookie file ready: %s (%d bytes)", Config.YTDLP_COOKIES_FILE, size)
    except OSError:
        logger.warning("yt-dlp cookie file path exists in config but could not be stat'ed: %s", Config.YTDLP_COOKIES_FILE)
else:
    logger.warning(
        "No YouTube cookies configured - extraction may hit "
        "'Sign in to confirm you're not a bot' errors, especially from a "
        "datacenter IP like Railway's."
    )


def _is_youtube_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "sign in to confirm you’re not a bot" in text
        or "sign in to confirm you're not a bot" in text
        or "use --cookies-from-browser or --cookies" in text
        or "confirm you're not a bot" in text
    )


def _extract_with_opts(query: str, video: bool, opts: dict) -> dict:
    logger.info("yt-dlp extracting: %s (player clients=%s)", query, opts.get("extractor_args", {}).get("youtube", {}).get("player_client"))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info.get("entries"):
            info = next((entry for entry in info["entries"] if entry), None)
        if not info:
            raise RuntimeError("yt-dlp returned no result for the requested media.")
        return info


def _extract(query: str, video: bool) -> dict:
    opts = _VIDEO_OPTS if video else _AUDIO_OPTS
    try:
        return _extract_with_opts(query, video, opts)
    except Exception as exc:
        if not _is_youtube_auth_error(exc):
            raise
        logger.warning("YouTube rejected the first client with an authentication/bot check; retrying with alternate clients.")

        # Retry without changing the cookie file or PO-token provider.
        # This handles sessions where YouTube rejects one player client but
        # accepts another with the same authenticated cookie jar.
        for client in ("web", "default"):
            retry_opts = dict(opts)
            retry_opts["extractor_args"] = {
                **opts.get("extractor_args", {}),
                "youtube": {
                    **opts.get("extractor_args", {}).get("youtube", {}),
                    "player_client": [client],
                },
            }
            try:
                return _extract_with_opts(query, video, retry_opts)
            except Exception as retry_exc:
                if not _is_youtube_auth_error(retry_exc):
                    raise
                logger.warning("YouTube rejected player client %s as well.", client)
        raise


_AUDIO_OPTS = {
    **_COMMON_OPTS,
    "format": "bestaudio/best",
}


_VIDEO_OPTS = {
    **_COMMON_OPTS,
    "format": "best[height<=480][ext=mp4]/best[height<=480]/best",
}


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
