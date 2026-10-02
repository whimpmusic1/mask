from pyrogram import Client

from config import Config

# The bot account - what users actually type commands to.
bot = Client(
    name="music-bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

# The assistant (userbot) account - the one that physically joins the
# voice chat and streams audio/video, since Bot API accounts cannot
# join group calls.
assistant = Client(
    name="assistant",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    session_string=Config.SESSION_STRING,
)
