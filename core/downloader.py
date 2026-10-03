import asyncio
import logging
import urllib.error
import urllib.request

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


def _preflight_check(url: str, headers: dict) -> None:
    """
    Verify the resolved stream URL is actually fetchable with its headers
    BEFORE handing it to PyTgCalls/ffmpeg.

    Why this exists: a warm-start re-kick (repeatedly calling play() after
    joining) did not fix reports of "joined the voice chat, UI says
    playing, but total silence for several minutes" - and on its 3rd
    retry it crashed inside PyTgCalls' own internals (reusing a
    MediaStream object across multiple play() calls corrupts its internal
    state). That ruled out "the connection just needs a nudge" as the
    explanation. The next most likely cause: yt-dlp resolves URLs through
    its own cookie/PO-token-aware HTTP stack, but ffmpeg (which is what
    actually fetches the audio once PyTgCalls starts playing) makes a
    plain request with only the headers we hand it - if those don't
    match what the URL actually requires, ffmpeg's fetch can be silently
    rejected while PyTgCalls still reports a successful *join* (joining
    the voice chat and fetching the media are two separate things).

    This makes that failure mode loud and immediate instead of 7 minutes
    of silence: fetch a small range of the URL with the exact headers
    ffmpeg will use, and raise a clear error before ever joining the call
    if it's rejected.
    """
    request_headers = dict(headers)
    request_headers.setdefault("Range", "bytes=0-8191")

    req = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            chunk = resp.read(1024)
            logger.info(
                "Stream URL preflight OK: status=%s bytes_read=%d",
                resp.status,
                len(chunk),
            )
            if not chunk:
                logger.warning(
                    "Stream URL preflight got status %s but ZERO bytes "
                    "back - this may still end up silent in playback.",
                    resp.status,
                )
    except urllib.error.HTTPError as e:
        logger.error(
            "Stream URL preflight FAILED: HTTP %s %s - ffmpeg would "
            "almost certainly have failed to fetch this too, which is "
            "what produces 'joined but silent' rather than a visible "
            "error. Headers sent: %s",
            e.code,
            e.reason,
            sorted(request_headers.keys()),
        )
        if e.code in (401, 403, 404):
            raise RuntimeError(
                f"The resolved stream link was rejected (HTTP {e.code}) "
                "when tested directly - it would not have played even "
                "though joining the voice chat would have looked fine."
            ) from e
    except Exception as e:
        # Don't hard-fail on non-HTTP errors (DNS blip, transient
        # timeout) - log it clearly and let playback attempt proceed,
        # since this check is a diagnostic/fast-fail aid, not a
        # guarantee either way.
        logger.error(
            "Stream URL preflight error (%s): %s - proceeding anyway, "
            "but if playback is silent this is the first place to look.",
            type(e).__name__,
            e,
        )


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

    result = {
        "title": info.get("title") or query,
        "duration": info.get("duration") or 0,
        "url": stream_url,
        "webpage_url": info.get("webpage_url"),
        "thumbnail": info.get("thumbnail"),
        "http_headers": info.get("http_headers") or {},
    }

    await loop.run_in_executor(
        None, _preflight_check, result["url"], result["http_headers"]
    )

    return result
