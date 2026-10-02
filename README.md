# Telegram Music Bot (VC Audio + Video Streaming)

A Telegram bot that streams audio **and** video into a group's voice chat,
built on:

- **Pyrogram** — Telegram MTProto client (bot + a "assistant" user account)
- **py-tgcalls (PyTgCalls)** — joins/streams into Telegram group voice chats
- **yt-dlp** — resolves search queries / links to a direct playable stream
- **ffmpeg** — required by pytgcalls under the hood to encode the stream

Telegram bot accounts are *not allowed* to join voice chats directly. That's
why there are two logins here:

- **the bot** (`BOT_TOKEN`) — what people type commands to
- **the assistant** (`SESSION_STRING`) — a normal user account that actually
  sits in the voice chat and streams the media

## 1. Get your credentials

1. **API_ID / API_HASH** — from <https://my.telegram.org> → "API Development Tools".
2. **BOT_TOKEN** — message [@BotFather](https://t.me/BotFather) → `/newbot`.
3. **SESSION_STRING** — run the helper script locally with a *real* Telegram
   account you're comfortable using as the "assistant" (ideally not your
   main personal account):
   ```bash
   pip install -r requirements.txt
   python generate_session.py
   ```
   Paste the resulting string into `.env`. Keep it secret — it's equivalent
   to a login for that account.

Copy `.env.sample` to `.env` and fill in all four values.

## 2. Install dependencies

You need **Python 3.10+** and **ffmpeg** installed on the machine.

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg   # Debian/Ubuntu
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> `py-tgcalls`'s API has changed across major versions. If `core/call.py`
> throws import errors after `pip install`, check the installed version
> (`pip show py-tgcalls`) against the examples in its GitHub repo and adjust
> the import names in `core/call.py` — the surrounding structure (queue,
> plugin loader, commands) doesn't need to change.

## 3. Run it

```bash
python bot.py
```

Then in your group:

1. Add **both** the bot and the assistant account to the group.
2. Start a voice chat.
3. `/play believer imagine dragons` for audio, or `/vplay ...` for video.

Full command list is in `plugins/start.py` / `/help`.

## 4. Deploying on Railway

This repository is Docker-ready for Railway. Railway will build the included
`Dockerfile` and run `python bot.py`. Add the following variables in the
Railway service settings:

```text
API_ID
API_HASH
BOT_TOKEN
SESSION_STRING
OWNER_IDS (comma-separated; legacy OWNER_ID is also accepted)
DURATION_LIMIT_MIN
VIDEO_QUALITY
```

Do not upload `.env` or Telegram session files to GitHub. Generate
`SESSION_STRING` locally with `generate_session.py`, then store it as a Railway
variable. Start by testing `/play`; test `/vplay` after audio playback works.

## Fixing "Sign in to confirm you're not a bot" (YouTube)

YouTube's anti-bot wall has gotten aggressive through 2026, especially
against requests from datacenter IPs (which is what Railway, and any cloud
host, gives you). Player-client swapping (`android`, `web_embedded`, `tv`,
etc.) and PO-token plugins like the bundled `bgutil` provider increasingly
aren't enough on their own anymore. The fix that still reliably works is
**cookies from a real, logged-in YouTube session**:

1. Install the **"Get cookies.txt LOCALLY"** browser extension
   (Chrome/Firefox).
2. Open a **private/incognito window** and sign in to YouTube with an
   account — ideally a throwaway one, not your main personal account,
   since you're handing a bot a snapshot of that session.
3. With the extension, export cookies for `youtube.com` as `cookies.txt`
   (Netscape format), then **close the private window** without browsing
   further (this "freezes" the session so it isn't rotated/invalidated
   before you use it).
4. Base64-encode the file so it's safe to paste into an env var:
   ```bash
   base64 -w0 cookies.txt        # Linux
   base64 -i cookies.txt         # macOS
   certutil -encode cookies.txt cookies.b64   # Windows (strip header/footer lines)
   ```
5. In Railway's **Variables** tab, add `YTDLP_COOKIES_B64` with that string.
   The bot also accepts the existing split form `YTDLP_COOKIES_B64_1` +
   `YTDLP_COOKIES_B64_2` for compatibility with the original deployment.
6. Redeploy. `config.py` decodes it to `/app/cookies.txt` at startup, and
   `core/downloader.py` automatically passes it to yt-dlp as `cookiefile`.
   You'll see `yt-dlp cookies file written to /app/cookies.txt` in the logs
   if it worked.

**Cookies expire.** If the bot-check error comes back after some weeks,
just re-export a fresh `cookies.txt` from a still-logged-in session and
update the Railway variable — no code changes needed.

**Why not just fix player_client/PO-tokens further?** You've already got
a correctly-wired `bgutil` PO-token server running alongside the bot
(good setup) — keep it, it doesn't hurt. But per that project's own
current notes, PO tokens alone no longer clear the bot-check in most
cases in 2026. Cookies are the layer that was actually missing.

### Keeping cookies from expiring so often

`core/cookie_refresher.py` runs as a background task and periodically
makes one real request to youtube.com using the existing cookies, so the
session gets renewed from normal use even if nobody plays anything for a
while. `config.py` only seeds `cookies.txt` from `YTDLP_COOKIES_B64` the
*first* time the file doesn't exist — after that, it's left alone so this
refresh can actually accumulate instead of being overwritten on every boot.

**Be clear-eyed about what this can't do.** This keeps an already-valid
session alive longer; it cannot bring back a session that's been fully
revoked (you logged out elsewhere, Google flagged the account, password
changed, etc.). There's no automatable, ToS-safe way to script past an
actual Google login/CAPTCHA/2FA challenge, and trying to fake one is the
kind of thing that gets accounts locked — so when it does eventually break,
you re-export `cookies.txt` by hand and update `YTDLP_COOKIES_B64` again,
the same as before. This script just makes that a once-in-a-while chore
instead of a weekly one.

**For this to survive redeploys, not just restarts:** Railway's filesystem
is ephemeral per-deploy by default, so a refreshed `cookies.txt` living at
`/app/cookies.txt` is lost the next time you push a change. Attach a
[Railway Volume](https://docs.railway.com/reference/volumes) to this
service (e.g. mounted at `/data`), set `YTDLP_COOKIES_PATH=/data/cookies.txt`,
and the refresher's progress will persist across deploys too — without a
Volume, you still get the benefit between restarts of the same deployment,
just not across a full redeploy.

## 5. Running with Docker instead

```bash
docker build -t music-bot .
docker run -d --restart unless-stopped --env-file .env --name music-bot music-bot
```

## Project layout

```
bot.py                 entry point, loads plugins, starts both clients
config.py              env-var driven settings
core/clients.py        the two Pyrogram Client singletons (bot + assistant)
core/call.py           PyTgCalls wrapper: join/stream/pause/skip/leave
core/queue.py          per-chat FIFO track queue
core/downloader.py     yt-dlp -> direct stream URL resolver
plugins/start.py       /start, /help
plugins/play.py        /play, /vplay
plugins/controls.py    /pause, /resume, /skip, /stop, /queue
deploy/music-bot.service   example systemd unit for a VPS
Dockerfile              container build (installs ffmpeg)
```

## Hosting this for $0/month

Streaming audio *and* video into a voice chat is genuinely CPU-hungry —
ffmpeg has to keep re-encoding a live stream continuously, and the process
has to stay connected 24/7. That rules out most "serverless"/free-tier PaaS
options, which either sleep the app when idle or cap monthly runtime hours.
What you actually need is a small **always-on VPS**. Ranked by fit:

### 1. Oracle Cloud "Always Free" tier — best option
Oracle's free tier isn't a trial — it's free indefinitely, and uniquely
generous:
- An **Ampere A1 (ARM)** shape: up to 4 OCPUs / 24 GB RAM, split across up to
  4 instances, free forever. Comfortably handles audio + video streaming.
- Or a smaller x86 **VM.Standard.E2.1.Micro**, always free but only 1 GB RAM
  (fine for audio-only; video will be tight).
- Setup: create an account (a card is required for identity verification but
  is not charged for Always-Free resources), spin up an Ubuntu VM, `ssh` in,
  install ffmpeg/Python/Docker, clone this repo, and run it under `systemd`
  (see `deploy/music-bot.service`) or Docker with `--restart unless-stopped`.
- Caveat: free ARM (A1) capacity is sometimes hard to get in busy regions on
  first signup — retry different regions if it says "out of capacity."

### 2. Google Cloud "Always Free" e2-micro — solid backup
One `e2-micro` instance (in specific US regions) is free forever, but it's
1 shared vCPU / 1 GB RAM — workable for audio, but video transcoding will
likely stutter or OOM under load. Good fallback if Oracle sign-up doesn't
work out.

### 3. A spare computer / Raspberry Pi at home
Literally $0 beyond electricity — full control, no vendor limits. Downsides:
depends on your home internet staying up, and you're responsible for keeping
it running (a `systemd` service + `Restart=always` handles most of that).

### Options to avoid for this specific bot
- **Render / Railway free plans** — apps sleep after inactivity or are
  capped on monthly hours; a voice-chat bot needs a persistent, always-open
  connection, so it'll get killed mid-stream.
- **Fly.io free allowance** — usable for audio-only at a squeeze (256 MB
  RAM per free VM), not realistic for video.
- **AWS free tier** — free for 12 months only, then billed; fine short-term,
  not a permanent $0 answer.

**Bottom line:** for audio *and* video together, get an Oracle Cloud
Always-Free Ampere A1 VM, install Docker or a Python venv, and run this bot
under `systemd`/`Restart=always` (or `docker run --restart unless-stopped`)
so it survives reboots and crashes with zero ongoing cost.

## Notes & responsibility

- Streaming copyrighted music/video through yt-dlp may violate YouTube's (or
  another source site's) Terms of Service depending on how you use it —
  that's on you to check for your use case and jurisdiction.
- `py-tgcalls` and `yt-dlp` both move fast; if YouTube changes something and
  extraction breaks, `pip install -U yt-dlp` is usually the first fix to try.
