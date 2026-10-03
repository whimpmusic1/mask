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


def start_keyboard(username: str = "", owner_username: str = ""):
    buttons = [[InlineKeyboardButton(
        "ADD ME TO YOUR GROUP", url=f"https://t.me/{username}?startgroup=true"
    )]] if username else []
    buttons.append([InlineKeyboardButton("Help", callback_data="start_help")])
    buttons.append([
        InlineKeyboardButton("Updates", url=Config.UPDATES_URL),
        InlineKeyboardButton("Group", url=Config.SUPPORT_URL),
    ])
    if Config.OWNER_ID:
        # Do not use InlineKeyboardButton(user_id=...). The installed
        # Pyrogram/PyrogramMod stack in Railway raises a constructor error
        # while serializing that field (InputKeyboardButtonUserProfile).
        # A public username is the compatible Telegram profile-link form.
        owner_username = (owner_username or Config.OWNER_USERNAME).strip().lstrip("@")
        if owner_username:
            buttons.append([InlineKeyboardButton(
                "👑 Owner", url=f"https://t.me/{owner_username}?profile"
            )])
        else:
            # This fallback keeps /start functional for private accounts that
            # have no username. The ID link is supported by Telegram inside an
            # inline keyboard, although clients may show an Open Link prompt.
            buttons.append([InlineKeyboardButton(
                "👑 Owner", url=f"tg://user?id={Config.OWNER_ID}"
            )])
    return InlineKeyboardMarkup(buttons)


async def _resolve_owner_username(client) -> str:
    if Config.OWNER_USERNAME:
        return Config.OWNER_USERNAME
    if not Config.OWNER_ID:
        return ""
    try:
        owner = await client.get_users(Config.OWNER_ID)
        return (owner.username or "").strip().lstrip("@")
    except Exception:
        return ""


@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    me = await client.get_me()
    owner_username = await _resolve_owner_username(client)
    await message.reply_text(
        WELCOME,
        reply_markup=start_keyboard(me.username or "", owner_username),
    )


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
    owner_username = await _resolve_owner_username(client)
    await callback_query.message.edit_text(
        WELCOME,
        reply_markup=start_keyboard(me.username or "", owner_username),
    )


@bot.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP)
