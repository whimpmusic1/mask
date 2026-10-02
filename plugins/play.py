from pyrogram import filters

from config import Config
from core.call import call
from core.clients import bot
from core.downloader import get_stream_info


@bot.on_message(filters.command(["play", "vplay"]))
async def play_cmd(client, message):
    if len(message.command) < 2:
        await message.reply_text(
            "Give me something to play, e.g.\n`/play believer imagine dragons`"
        )
        return

    query = message.text.split(None, 1)[1].strip()
    video = message.command[0] == "vplay"
    chat_id = message.chat.id

    status = await message.reply_text("🔎 Searching...")

    try:
        info = await get_stream_info(query, video=video)
    except Exception as e:
        await status.edit_text(f"Couldn't find or resolve that: `{e}`")
        return

    duration_min = (info["duration"] or 0) / 60
    if duration_min > Config.DURATION_LIMIT_MIN:
        await status.edit_text(
            f"That's {duration_min:.0f} min long, which is over the "
            f"{Config.DURATION_LIMIT_MIN} min limit set in .env. Pick something shorter."
        )
        return

    track = {
        "url": info["url"],
        "title": info["title"],
        "duration": info["duration"],
        "video": video,
        "requested_by": message.from_user.mention if message.from_user else "someone",
    }

    try:
        state = await call.add_and_play(chat_id, track)
    except Exception as e:
        await status.edit_text(
            "Couldn't join the voice chat. Double-check that:\n"
            "1. A voice chat is currently active in this group\n"
            "2. The *assistant* account (not just the bot) is a member here\n\n"
            f"Error: `{e}`"
        )
        return

    kind = "video" if video else "audio"
    if state == "playing":
        await status.edit_text(f"▶️ Now playing ({kind}): **{info['title']}**")
    else:
        await status.edit_text(f"➕ Queued ({kind}): **{info['title']}**")
