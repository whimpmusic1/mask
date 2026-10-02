from pyrogram import filters

from core.call import call
from core.clients import bot


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
