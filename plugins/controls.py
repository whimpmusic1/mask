from pyrogram import filters
import logging
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

import core.call as call_module
from core.clients import bot
logger = logging.getLogger(__name__)
PLAYER_MESSAGES: dict[int, int] = {}

def remember_player_message(chat_id: int, message_id: int) -> None:
    PLAYER_MESSAGES[chat_id] = message_id
    
def _format_now_playing(track: dict) -> str:
    kind = "video" if track.get("video") else "audio"
    duration = int(track.get("duration") or 0)
    mins, secs = divmod(duration, 60)

    return (
        f"🎶 **Now playing ({kind})**\n\n"
        f"**{track.get('title', 'Unknown track')}**\n"
        f"⏱ {mins}:{secs:02d}\n"
        f"👤 Requested by {track.get('requested_by', 'someone')}"
    )
async def _update_now_playing_message(chat_id: int, track):
    """Create/update one player panel; thumbnail failures never break playback."""
    message_id = PLAYER_MESSAGES.get(chat_id)
    finished_text = "⏹ **Playback finished**\n\nThe queue is empty."

    if not track:
        if message_id:
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id,
                    caption=finished_text, reply_markup=None,
                )
            except Exception:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=finished_text, reply_markup=None,
                    )
                except Exception:
                    pass
        return

    caption = _format_now_playing(track)
    thumbnail = track.get("thumbnail")
    markup = player_keyboard(chat_id)

    if message_id is None:
        msg = None
        if thumbnail:
            try:
                msg = await bot.send_photo(
                    chat_id=chat_id, photo=thumbnail, caption=caption,
                    reply_markup=markup,
                )
            except Exception as exc:
                logger.warning("Player thumbnail send failed in %s; using text panel: %s", chat_id, exc)
        if msg is None:
            msg = await bot.send_message(chat_id=chat_id, text=caption, reply_markup=markup)
        PLAYER_MESSAGES[chat_id] = msg.id
        return

    # Replace artwork whenever possible. If Telegram rejects the thumbnail,
    # delete the old photo panel and recreate a text panel so stale artwork
    # cannot be mistaken for the current track.
    if thumbnail:
        try:
            await bot.edit_message_media(
                chat_id=chat_id, message_id=message_id,
                media=InputMediaPhoto(media=thumbnail, caption=caption),
                reply_markup=markup,
            )
            return
        except Exception as exc:
            logger.warning("Player media edit failed in %s; falling back to text: %s", chat_id, exc)
    else:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=caption, reply_markup=markup,
            )
            return
        except Exception:
            pass

    try:
        await bot.delete_messages(chat_id, message_id)
    except Exception:
        pass
    msg = await bot.send_message(chat_id=chat_id, text=caption, reply_markup=markup)
    PLAYER_MESSAGES[chat_id] = msg.id

def player_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    looping = call_module.call.get_loop_remaining(chat_id) > 0
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸ Pause", callback_data="player_pause"),
            InlineKeyboardButton("▶️ Resume", callback_data="player_resume"),
            InlineKeyboardButton("⏭ Skip", callback_data="player_skip"),
        ],
        [
            InlineKeyboardButton(f"🔁 Loop: {'ON' if looping else 'OFF'}", callback_data="loop_toggle"),
            InlineKeyboardButton("⏹ Stop", callback_data="player_stop"),
        ],
    ])


async def _refresh_player(message):
    try:
        await message.edit_reply_markup(reply_markup=player_keyboard(message.chat.id))
    except Exception:
        # Telegram rejects unchanged markup and messages that are no longer editable.
        pass


@bot.on_message(filters.command("loop"))
async def loop_cmd(client, message):
    enabled = call_module.call.toggle_loop(message.chat.id)
    if not enabled and call_module.call.get_queue(message.chat.id).current() is None:
        await message.reply_text("Nothing is playing to loop.")
        return
    await message.reply_text(f"Loop is now **{'ON 🔁' if enabled else 'OFF'}**.")


@bot.on_callback_query(filters.regex("^loop_toggle$"))
async def loop_button(client, callback_query):
    chat_id = callback_query.message.chat.id
    enabled = call_module.call.toggle_loop(chat_id)
    await callback_query.answer("Loop " + ("ON 🔁" if enabled else "OFF"))
    await _refresh_player(callback_query.message)


@bot.on_message(filters.command("pause"))
async def pause_cmd(client, message):
    await call_module.call.pause(message.chat.id)
    await message.reply_text("⏸ Paused.")


@bot.on_message(filters.command("resume"))
async def resume_cmd(client, message):
    await call_module.call.resume(message.chat.id)
    await message.reply_text("▶️ Resumed.")


@bot.on_message(filters.command("skip"))
async def skip_cmd(client, message):
    await call_module.call.skip(message.chat.id)
    await message.reply_text("⏭ Skipped.")


@bot.on_message(filters.command("stop"))
async def stop_cmd(client, message):
    await call_module.call.leave(message.chat.id)
    await message.reply_text("⏹ Stopped and left the voice chat.")


@bot.on_message(filters.command("queue"))
async def queue_cmd(client, message):
    queue = call_module.call.get_queue(message.chat.id)
    if not queue.tracks:
        await message.reply_text("Queue is empty.")
        return
    lines = []
    for i, track in enumerate(queue.tracks, start=1):
        prefix = "▶️" if i == 1 else f"{i}."
        lines.append(f"{prefix} {track.get('title', 'Unknown track')}")
    await message.reply_text("**Queue:**\n" + "\n".join(lines))


@bot.on_message(filters.command("now"))
async def now_cmd(client, message):
    track = call_module.call.get_queue(message.chat.id).current()
    if not track:
        await message.reply_text("Nothing is playing right now.")
        return
    duration = int(track.get("duration") or 0)
    mins, secs = divmod(duration, 60)
    requester = track.get("requested_by", "someone")
    await message.reply_text(
        f"🎶 **Now playing**\n\n**{track.get('title', 'Unknown track')}**\n"
        f"⏱ {mins}:{secs:02d}\n👤 Requested by {requester}",
        reply_markup=player_keyboard(message.chat.id),
    )


@bot.on_callback_query(filters.regex(r"^player_(pause|resume|skip|stop)$"))
async def player_button(client, callback_query):
    chat_id = callback_query.message.chat.id
    action = callback_query.data.removeprefix("player_")
    try:
        if action == "pause":
            await call_module.call.pause(chat_id)
            notice = "Paused."
        elif action == "resume":
            await call_module.call.resume(chat_id)
            notice = "Resumed."
        elif action == "skip":
            await call_module.call.skip(chat_id)
            notice = "Skipped."
        else:
            await call_module.call.leave(chat_id)
            notice = "Stopped."
        await callback_query.answer(notice)
        if action != "stop":
            await _refresh_player(callback_query.message)
    except Exception as exc:
        await callback_query.answer(f"Playback action failed: {exc}", show_alert=True)
