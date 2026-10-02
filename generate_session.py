"""
Run this once, locally, to generate the SESSION_STRING for your assistant
(userbot) account. This account is what actually joins the voice chat -
Telegram bots are not allowed to join group calls directly.

    python generate_session.py

Use a real Telegram account for this - ideally not your personal main
account, since it will sit in voice chats and play media. Keep the
resulting string secret; anyone who has it can log in as that account.
"""

from pyrogram import Client

api_id = int(input("API ID: ").strip())
api_hash = input("API Hash: ").strip()

with Client("session_generator", api_id=api_id, api_hash=api_hash, in_memory=True) as app:
    session_string = app.export_session_string()
    print("\nYour SESSION_STRING (copy this into .env):\n")
    print(session_string)
    print("\nKeep it secret - do not commit it or share it anywhere.")
