from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import Config
from core.clients import bot

WELCOME = (
    "🎵 **Music Bot is online**\n\n"
    "1. Add me *and* my assistant account to your group.\n"
    "2. Make the assistant account an admin (or at least a member) of the group.\n"
    "3. Start a voice chat in the group.\n"
    "4. Send `/play <song name or link>` for audio.\n\n"
    "Use the buttons below to explore the bot."
)
HELP = (
    "**Commands**\n\n"
    "`/play <query>` - play/queue audio\n"
    "`/vplay <query>` - play/queue video\n"
    "`/now` - show current track and controls\n"
    "`/pause` - pause playback\n"
    "`/resume` - resume playback\n"
    "`/skip` - skip the current track\n"
    "`/stop` - stop playback and leave\n"
    "`/queue` - show the queue\n"
    "`/loop` - toggle repeat of the current track\n"
    "`/restart` - restart the bot (owners only)"
)


def start_keyboard(username: str = ""):
    buttons = [[InlineKeyboardButton(
        "ADD ME TO YOUR GROUP", url=f"https://t.me/{username}?startgroup=true"
    )]] if username else []
    buttons.append([InlineKeyboardButton("Help", callback_data="start_help")])
    buttons.append([
        InlineKeyboardButton("Updates", url=Config.UPDATES_URL),
        InlineKeyboardButton("Group", url=Config.SUPPORT_URL),
    ])
    if Config.OWNER_ID:
        # Use Telegram's native user-profile button instead of a tg:// URL.
        # PyrogramMod 2.4.1 maps user_id to keyboardButtonUserProfile,
        # which opens the owner's profile directly without the external-link
        # confirmation dialog shown by tg:// URL buttons.
        buttons.append([InlineKeyboardButton(
            "👑 Owner", user_id=Config.OWNER_ID
        )])
    return InlineKeyboardMarkup(buttons)


@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    me = await client.get_me()
    await message.reply_text(WELCOME, reply_markup=start_keyboard(me.username or ""))


@bot.on_callback_query(filters.regex("^start_help$"))
async def help_button(client, callback_query):
    await callback_query.answer()
    await callback_query.message.edit_text(
        HELP, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="start_back")]])
    )


@bot.on_callback_query(filters.regex("^start_back$"))
async def back_button(client, callback_query):
    await callback_query.answer()
    me = await client.get_me()
    await callback_query.message.edit_text(WELCOME, reply_markup=start_keyboard(me.username or ""))


@bot.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP)
