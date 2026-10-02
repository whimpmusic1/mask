from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import core.call as call_module
from core.clients import bot


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
