def _write_cookies_file() -> str | None:
    path = os.environ.get("YTDLP_COOKIES_PATH", "/app/cookies.txt")

    b64_1 = os.environ.get("YTDLP_COOKIES_B64_1", "").strip()
    b64_2 = os.environ.get("YTDLP_COOKIES_B64_2", "").strip()

    b64 = b64_1 + b64_2

    if not b64:
        b64 = os.environ.get("YTDLP_COOKIES_B64", "").strip()

    if not b64:
        if os.path.exists(path):
            log.info("Using existing yt-dlp cookies file at %s.", path)
            return path
        return None

    try:
        raw = base64.b64decode(b64, validate=True)

        first_line = raw.splitlines()[0].decode("utf-8", errors="replace").strip()
        if first_line not in (
            "# HTTP Cookie File",
            "# Netscape HTTP Cookie File",
        ):
            raise ValueError(
                f"Invalid cookies.txt header: {first_line!r}"
            )

        tmp_path = f"{path}.tmp"

        with open(tmp_path, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)

        log.info(
            "yt-dlp cookies seeded from Railway variables: %s (%d bytes)",
            path,
            len(raw),
        )
        return path

    except Exception:
        log.exception("Failed to create a valid yt-dlp cookies file")
        return None
