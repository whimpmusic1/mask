from pyrogram import filters
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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
    "`/pause` - pause the current stream\n"
    "`/resume` - resume playback\n"
    "`/skip` - skip the current track\n"
    "`/stop` - stop playback and leave\n"
    "`/queue` - show the queue\n"
    "`/loop` - toggle repeat of the current track\n"
    "`/restart` - restart the bot *(owners only)*\n"
)


def start_keyboard():
    buttons = [
        [
            InlineKeyboardButton(
                "ADD ME TO YOUR GROUP",
                url="https://t.me/{0}?startgroup=true",
            )
        ],
        [
            InlineKeyboardButton(
                "Help",
                callback_data="start_help",
            )
        ],
        [
            InlineKeyboardButton(
                "Updates",
                url="https://t.me/YOUR_UPDATES_CHANNEL",
            ),
            InlineKeyboardButton(
                "Group",
                url="https://t.me/YOUR_SUPPORT_GROUP",
            ),
        ],
    ]

    if Config.OWNER_ID:
        buttons.append(
            [
                InlineKeyboardButton(
                    "👑 Owner",
                    url=f"tg://user?id={Config.OWNER_ID}",
                )
            ]
        )

    return InlineKeyboardMarkup(buttons)


@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    me = await client.get_me()

    keyboard = [
        [
            InlineKeyboardButton(
                "ADD ME TO YOUR GROUP",
                url=f"https://t.me/{me.username}?startgroup=true",
            )
        ],
        [
            InlineKeyboardButton(
                "Help",
                callback_data="start_help",
            )
        ],
        [
            InlineKeyboardButton(
                "Updates",
                url="https://t.me/YOUR_UPDATES_CHANNEL",
            ),
            InlineKeyboardButton(
                "Group",
                url="https://t.me/YOUR_SUPPORT_GROUP",
            ),
        ],
    ]

    if Config.OWNER_ID:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "👑 Owner",
                    url=f"tg://user?id={Config.OWNER_ID}",
                )
            ]
        )

    await message.reply_text(
        WELCOME,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@bot.on_callback_query(filters.regex("^start_help$"))
async def help_button(client, callback_query):
    await callback_query.answer()

    await callback_query.message.edit_text(
        HELP,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="start_back",
                    )
                ]
            ]
        ),
    )


@bot.on_callback_query(filters.regex("^start_back$"))
async def back_button(client, callback_query):
    await callback_query.answer()

    me = await client.get_me()

    keyboard = [
        [
            InlineKeyboardButton(
                "ADD ME TO YOUR GROUP",
                url=f"https://t.me/{me.username}?startgroup=true",
            )
        ],
        [
            InlineKeyboardButton(
                "Help",
                callback_data="start_help",
            )
        ],
        [
            InlineKeyboardButton(
                "Updates",
                url="https://t.me/psycho_dv",
            ),
            InlineKeyboardButton(
                "Group",
                url="https://t.me/+pra5-89rnZoxYzQ1",
            ),
        ],
    ]

    if Config.OWNER_ID:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "👑 Owner",
                    url=f"tg://user?id={Config.OWNER_ID}",
                )
            ]
        )

    await callback_query.message.edit_text(
        WELCOME,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@bot.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP)
