import asyncio
import os
import sys

from pyrogram import filters

from config import Config
from core.clients import bot


def is_owner(message) -> bool:
    return bool(
        message.from_user
        and message.from_user.id in Config.OWNER_IDS
    )


@bot.on_message(filters.command("restart"))
async def restart_cmd(client, message):
    if not is_owner(message):
        await message.reply_text(
            "❌ This command is available only to the bot owners."
        )
        return

    await message.reply_text(
        "🔄 **Restarting bot...**"
    )

    await asyncio.sleep(1.5)

    os.execv(
        sys.executable,
        [sys.executable, os.path.abspath("bot.py")],
    )
