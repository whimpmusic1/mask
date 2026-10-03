from pyrogram import filters

from config import Config
import core.call as call_module
from core.clients import bot
from core.downloader import get_stream_info
from plugins.controls import _update_now_playing_message


@bot.on_message(filters.command(["play", "vplay"]) & filters.group)
async def play_cmd(client, message):

    if len(message.command) < 2:
        await message.reply_text(
            "Give me something to play, e.g.\n"
            "/play chandni"
        )
        return

    query = message.text.split(None, 1)[1].strip()

    video = message.command[0].lower() == "vplay"
    chat_id = message.chat.id

    status = await message.reply_text("🔎 Searching...")

    try:
        info = await get_stream_info(
            query,
            video=video,
        )
    except Exception as e:
        await status.edit_text(
            f"Couldn't find or resolve that:\n{e}"
        )
        return

    duration_min = (info.get("duration") or 0) / 60

    if duration_min > Config.DURATION_LIMIT_MIN:
        await status.edit_text(
            f"That's {duration_min:.0f} min long, which is over "
            f"the {Config.DURATION_LIMIT_MIN} min limit set in .env. "
            "Pick something shorter."
        )
        return

    track = {
        "url": info["url"],
        "title": info["title"],
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail"),
        "video": video,
        "requested_by": (
            message.from_user.mention
            if message.from_user
            else "someone"
        ),
    }

    try:
        state = await call_module.call.add_and_play(
            chat_id,
            track,
        )
    except Exception as e:
        await status.edit_text(
            "Couldn't join the voice chat. Double-check that:\n"
            "1. A voice chat is currently active in this group\n"
            "2. The assistant account is a member of this group\n\n"
            f"Error:\n{e}"
        )
        return

    kind = "video" if video else "audio"

    if state == "playing":
        try:
            await status.delete()
        except Exception:
            pass
        # The Call layer owns the shared player message and updates it on every
        # track transition; this also repairs the panel after a fresh /play.
        await _update_now_playing_message(chat_id, track)
    else:
        await status.edit_text(
            f"➕ Queued ({kind}): {info['title']}\n"
            f"Use /queue to view the playlist."
        )
