from pyrogram import filters

from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from core.call import call
from core.clients import bot

@bot.on_message(filters.command("loop"))
async def loop_cmd(client, message):
    enabled = call.toggle_loop(message.chat.id)

    state = "ON 🔁" if enabled else "OFF"

    await message.reply_text(
        f"Loop is now **{state}**."
    )


@bot.on_callback_query(filters.regex("^loop_toggle$"))
async def loop_button(client, callback_query):
    chat_id = callback_query.message.chat.id

    enabled = call.toggle_loop(chat_id)

    state = "ON 🔁" if enabled else "OFF"

    await callback_query.answer(
        f"Loop {state}",
        show_alert=False,
    )

    try:
        await callback_query.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"🔁 Loop: {'ON' if enabled else 'OFF'}",
                            callback_data="loop_toggle",
                        )
                    ]
                ]
            )
        )
    except Exception:
        pass

@bot.on_message(filters.command("pause"))
async def pause_cmd(client, message):
    await call.pause(message.chat.id)
    await message.reply_text("⏸ Paused.")


@bot.on_message(filters.command("resume"))
async def resume_cmd(client, message):
    await call.resume(message.chat.id)
    await message.reply_text("▶️ Resumed.")


@bot.on_message(filters.command("skip"))
async def skip_cmd(client, message):
    await call.skip(message.chat.id)
    await message.reply_text("⏭ Skipped.")


@bot.on_message(filters.command("stop"))
async def stop_cmd(client, message):
    await call.leave(message.chat.id)
    await message.reply_text("⏹ Stopped and left the voice chat.")


@bot.on_message(filters.command("queue"))
async def queue_cmd(client, message):
    queue = call.get_queue(message.chat.id)
    if not queue.tracks:
        await message.reply_text("Queue is empty.")
        return

    lines = [f"{i}. {t['title']}" for i, t in enumerate(queue.tracks, start=1)]
    await message.reply_text("**Queue:**\n" + "\n".join(lines))
