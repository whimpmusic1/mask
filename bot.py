import asyncio
import importlib
import logging
import pkgutil

import plugins

from core import call as call_module
from core import cookie_refresher
from core.clients import assistant, bot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logging.getLogger("pyrogram").setLevel(logging.WARNING)


def load_plugins():
    for _, name, _ in pkgutil.iter_modules(plugins.__path__):
        importlib.import_module(f"plugins.{name}")


async def main():
    logging.info("Starting Telegram clients...")

    # Start the clients inside the asyncio loop created by asyncio.run().
    await bot.start()

    logging.info("Bot client started.")

    await assistant.start()

    logging.info("Assistant client started.")

    # IMPORTANT:
    # Create PyTgCalls AFTER asyncio.run() has created the active loop
    # and AFTER the assistant client has started.
    call = call_module.create_call(assistant)

    logging.info("PyTgCalls instance created.")

    await call.start()

    logging.info("PyTgCalls started.")

    # Load plugins only after the global `call` object exists.
    load_plugins()

    # Background task: periodically keeps the yt-dlp cookie session warm
    # so it doesn't go stale from pure inactivity between manual re-exports.
    # See core/cookie_refresher.py for exactly what this can and can't do.
    asyncio.create_task(cookie_refresher.run_forever())

    logging.info(
        "Music bot is live - audio-only voice-chat streaming ready."
    )

    try:
        # Keep Railway worker alive.
        await asyncio.Event().wait()

    finally:
        logging.info("Shutting down music bot...")

        try:
            if call is not None:
                # PyTgCalls 2.3.3 does not necessarily expose a separate
                # stop() API that we need here. Leaving active calls and
                # stopping the Pyrogram clients is sufficient for shutdown.
                pass

        except Exception:
            logging.exception(
                "Failed during PyTgCalls shutdown"
            )

        try:
            await assistant.stop()

        except Exception:
            logging.exception(
                "Failed to stop assistant cleanly"
            )

        try:
            await bot.stop()

        except Exception:
            logging.exception(
                "Failed to stop bot cleanly"
            )


if __name__ == "__main__":
    asyncio.run(main())
