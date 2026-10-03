import logging

from pyrogram import filters
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
    message_id = PLAYER_MESSAGES.get(chat_id)

    if not track:
        if message_id:
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption="⏹ **Playback finished**\n\nThe queue is empty.",
                    reply_markup=None,
                )
            except Exception:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="⏹ **Playback finished**\n\nThe queue is empty.",
                        reply_markup=None,
                    )
                except Exception:
                    pass

        PLAYER_MESSAGES.pop(chat_id, None)
        return

    caption = _format_now_playing(track)
    thumbnail = track.get("thumbnail")

    if not thumbnail:
        logger.info(
            "No thumbnail on track %r for chat %s - rendering text-only.",
            track.get("title"),
            chat_id,
        )

    # No existing player message.
    if message_id is None:
        if thumbnail:
            try:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=thumbnail,
                    caption=caption,
                    reply_markup=player_keyboard(chat_id),
                )
                PLAYER_MESSAGES[chat_id] = msg.id
                return
            except Exception:
                logger.exception(
                    "send_photo with thumbnail failed for chat %s "
                    "(thumbnail url: %r) - falling back to text.",
                    chat_id,
                    thumbnail,
                )

        msg = await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=player_keyboard(chat_id),
        )
        PLAYER_MESSAGES[chat_id] = msg.id
        return

    # Existing player message is a photo.
    if thumbnail:
        try:
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(
                    media=thumbnail,
                    caption=caption,
                ),
                reply_markup=player_keyboard(chat_id),
            )
            return
        except Exception:
            logger.exception(
                "edit_message_media with thumbnail failed for chat %s "
                "(thumbnail url: %r) - falling back to caption-only edit.",
                chat_id,
                thumbnail,
            )

    # Fallback if the old message was text, or the photo edit above failed.
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=player_keyboard(chat_id),
        )
    except Exception:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=caption,
                reply_markup=player_keyboard(chat_id),
            )
        except Exception:
            logger.exception(
                "Could not update the player message at all for chat %s",
                chat_id,
            )

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
    # call.skip() internally calls _play_next(), which fires
    # on_track_change -> _update_now_playing_message - the player card
    # updates to the next track (or "Playback finished") on its own, so
    # there's nothing else to render here.
    await call_module.call.skip(message.chat.id)


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
            # call.skip() fires on_track_change -> _update_now_playing_message,
            # which re-renders this same card (new track, or "Playback
            # finished" if the queue is now empty) - nothing more to do here.
            await call_module.call.skip(chat_id)
            notice = "Skipped."
        else:
            # call.leave() also fires on_track_change -> clears the card.
            await call_module.call.leave(chat_id)
            notice = "Stopped."

        await callback_query.answer(notice)

        # Pause/resume don't change the track, just refresh the markup
        # (currently a no-op since the keyboard doesn't vary by play state,
        # but harmless and keeps this correct if that ever changes).
        if action in ("pause", "resume"):
            await _refresh_player(callback_query.message)

    except Exception as exc:
        await callback_query.answer(f"Playback action failed: {exc}", show_alert=True)


# Self-register as the hook that renders the player card whenever playback
# state changes (initial play, skip, a track ending naturally, stop).
# Done here - at the bottom of this module, at import time - rather than
# as a separate step in bot.py: plugins are only ever loaded (via
# load_plugins() in bot.py) after core.call.create_call() has already run,
# so call_module.call is guaranteed to exist by the time this line runs.
# Keeping the wiring inside the plugin that owns the UI means there's no
# separate step to forget when only this file changes.
if call_module.call is not None:
    call_module.call.on_track_change = _update_now_playing_message
    logger.info("Player UI hook registered on the Call instance.")
else:
    logger.error(
        "core.call.call was None when plugins/controls.py loaded - the "
        "player card will not update automatically. This means plugins "
        "loaded before create_call() ran, which shouldn't happen; check "
        "bot.py's startup order."
    )
