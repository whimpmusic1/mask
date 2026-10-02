from pyrogram import filters

from core.clients import bot

WELCOME = (
    "🎵 **Music Bot is online**\n\n"
    "1. Add me *and* my assistant account to your group.\n"
    "2. Make the assistant account an admin (or at least a member) of the group.\n"
    "3. Start a voice chat in the group.\n"
    "4. Send `/play <song name or link>` for audio, or `/vplay <name or link>` for video.\n\n"
    "Send /help to see every command."
)

HELP = (
    "**Commands**\n\n"
    "`/play <query>` - play/queue audio in the voice chat\n"
    "`/vplay <query>` - play/queue video in the voice chat\n"
    "`/pause` - pause the current stream\n"
    "`/resume` - resume a paused stream\n"
    "`/skip` - skip to the next queued track\n"
    "`/stop` - stop playback and leave the voice chat\n"
    "`/queue` - show what's queued up\n"
)


@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(WELCOME)


@bot.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP)
