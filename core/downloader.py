import asyncio
import logging
import os
import uuid

import yt_dlp

from config import Config

logger = logging.getLogger(__name__)

# Downloaded audio files live here, named by video id so repeat requests
# in quick succession don't collide, and so cleanup (see core/call.py) is
# a simple, reliable path lookup.
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/app/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


_COMMON_OPTS = {
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "geo_bypass": True,
    "nocheckcertificate": True,

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
        size = os.path.getsize(Config.YTDLP_COOKIES_FILE)
        logger.info("yt-dlp cookie file ready: %s (%d bytes)", Config.YTDLP_COOKIES_FILE, size)
    except OSError:
        logger.warning("yt-dlp cookie file path exists in config but could not be stat'ed: %s", Config.YTDLP_COOKIES_FILE)
else:
    logger.warning(
        "No YouTube cookies configured - extraction may hit "
        "'Sign in to confirm you're not a bot' errors, especially from a "
        "datacenter IP like Railway's."
    )


# IMPORTANT architectural note (why this file downloads instead of
# streaming a raw URL):
#
# The original version of this module resolved a direct CDN URL and
# headers, and handed those straight to PyTgCalls/ffmpeg to fetch live at
# play() time. That produced a reproducible bug: the voice chat join
# would succeed and the UI would say "Now playing", but audio was
# silent - sometimes for the track's entire duration - because the
# actual media fetch (done separately by ffmpeg, with only the headers
# we passed it) could fail or stall in ways that never surfaced as a
# visible error. A warm-start retry workaround didn't fix it and
# eventually crashed PyTgCalls' internals; a URL-reachability preflight
# check didn't conclusively explain it either.
#
# Comparing against a known-working, widely-deployed Telegram music bot
# (same pytgcalls/ffmpeg stack) showed it never streams a raw remote URL
# at all for regular tracks - it downloads the file to local disk first,
# then plays that local file. That sidesteps the entire class of
# problem by construction: there is no live HTTP fetch happening at
# play() time, so there's nothing for ffmpeg/pytgcalls to get stuck on.
# This module now does the same thing.

_AUDIO_OPTS = {
    **_COMMON_OPTS,
    "format": "bestaudio/best",
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        # Opus is what Telegram voice chats use natively, so this also
        # keeps file size down and avoids an extra transcode step later.
        "preferredcodec": "opus",
        "preferredquality": "128",
    }],
}

_VIDEO_OPTS = {
    **_COMMON_OPTS,
    "format": "best[height<=480][ext=mp4]/best[height<=480]/best",
    "merge_output_format": "mp4",
}


def _is_youtube_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "sign in to confirm you’re not a bot" in text
        or "sign in to confirm you're not a bot" in text
        or "use --cookies-from-browser or --cookies" in text
        or "confirm you're not a bot" in text
    )


def _expected_output_path(info: dict, video: bool, request_dir: str) -> str:
    video_id = info["id"]
    if video:
        return os.path.join(request_dir, f"{video_id}_video.mp4")
    return os.path.join(request_dir, f"{video_id}.opus")


def _download_with_opts(query: str, video: bool, opts: dict) -> dict:
    logger.info(
        "yt-dlp downloading: %s (player clients=%s)",
        query,
        opts.get("extractor_args", {}).get("youtube", {}).get("player_client"),
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if info.get("entries"):
            info = next((entry for entry in info["entries"] if entry), None)
        if not info:
            raise RuntimeError("yt-dlp returned no result for the requested media.")
        return info


def _download(query: str, video: bool) -> dict:
    # A unique directory per request/download - never shared across
    # chats or concurrent requests, so one chat's cleanup can never
    # delete a file another chat is actively streaming, and simultaneous
    # downloads of the identical video never collide on disk.
    request_dir = os.path.join(DOWNLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(request_dir, exist_ok=True)

    base_opts = _VIDEO_OPTS if video else _AUDIO_OPTS
    outtmpl = os.path.join(
        request_dir, "%(id)s_video.%(ext)s" if video else "%(id)s.%(ext)s"
    )
    opts = {**base_opts, "outtmpl": outtmpl}

    try:
        info = _download_with_opts(query, video, opts)
    except Exception as exc:
        if not _is_youtube_auth_error(exc):
            raise
        logger.warning("YouTube rejected the first client with an authentication/bot check; retrying with alternate clients.")

        info = None
        last_exc = exc
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
                info = _download_with_opts(query, video, retry_opts)
                break
            except Exception as retry_exc:
                last_exc = retry_exc
                if not _is_youtube_auth_error(retry_exc):
                    raise
                logger.warning("YouTube rejected player client %s as well.", client)
        if info is None:
            raise last_exc

    file_path = _expected_output_path(info, video, request_dir)
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        raise RuntimeError(
            f"yt-dlp reported success but the expected output file is "
            f"missing or empty: {file_path}"
        )

    logger.info(
        "Download complete: %s (%d bytes) for %r",
        file_path,
        os.path.getsize(file_path),
        info.get("title"),
    )

    return {
        "title": info.get("title") or query,
        "duration": info.get("duration") or 0,
        "file_path": file_path,
        "webpage_url": info.get("webpage_url"),
        "thumbnail": info.get("thumbnail"),
    }


async def get_stream_info(query: str, video: bool = False) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download, query, video)
