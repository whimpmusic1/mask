import logging

import pyrogram.errors

# PyTgCalls 2.3.3 expects this older error name.
# Newer Pyrogram versions expose GroupCallForbidden instead.
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    if hasattr(pyrogram.errors, "GroupCallForbidden"):
        pyrogram.errors.GroupcallForbidden = (
            pyrogram.errors.GroupCallForbidden
        )

from pytgcalls import PyTgCalls
from pytgcalls import filters as fl
from pytgcalls.types import AudioQuality, MediaStream, StreamEnded

from core.queue import MusicQueue

logger = logging.getLogger(__name__)


class Call:
    """PyTgCalls wrapper with a per-chat FIFO audio queue."""

    def __init__(self, assistant_client):
        # IMPORTANT:
        # Create this inside the running asyncio event loop.
        self.pytgcalls = PyTgCalls(assistant_client)

        self.queues: dict[int, MusicQueue] = {}

        # Number of additional times the current song should repeat.
        # Example:
        # /loop 5 -> current song repeats 5 additional times.
        self.loop_remaining: dict[int, int] = {}

        self._register_handlers()

    def get_queue(self, chat_id: int) -> MusicQueue:
        if chat_id not in self.queues:
            self.queues[chat_id] = MusicQueue()

        return self.queues[chat_id]

    def _register_handlers(self):
        @self.pytgcalls.on_update(fl.stream_end())
        async def _on_stream_end(client, update: StreamEnded):
            chat_id = update.chat_id

            logger.info(
                "Stream ended in chat %s",
                chat_id,
            )

            # Repeat the current track if loop count is active.
            remaining = self.loop_remaining.get(chat_id, 0)

            if remaining > 0:
                queue = self.get_queue(chat_id)
                current = queue.current()

                if current is not None:
                    self.loop_remaining[chat_id] = remaining - 1

                    logger.info(
                        "Looping current track in chat %s. "
                        "Remaining repeats: %s",
                        chat_id,
                        remaining - 1,
                    )

                    try:
                        await self._stream(
                            chat_id,
                            current,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to loop current track in chat %s",
                            chat_id,
                        )
                        await self.leave(chat_id)

                    return

            # Normal queue behaviour.
            self.loop_remaining.pop(chat_id, None)

            await self._play_next(chat_id)

    def _build_stream(self, url: str) -> MediaStream:
        return MediaStream(
            url,
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.IGNORE,
        )

    async def start(self):
        await self.pytgcalls.start()

    async def _stream(self, chat_id: int, track: dict):
        """Start an audio stream."""

        stream = self._build_stream(track["url"])

        try:
            await self.pytgcalls.play(
                chat_id,
                stream,
            )

            logger.info(
                "Started audio stream in chat %s: %s",
                chat_id,
                track["title"],
            )

        except Exception:
            logger.exception(
                "Failed to start stream in chat %s: %s",
                chat_id,
                track["title"],
            )
            raise

    async def _play_next(self, chat_id: int):
        queue = self.get_queue(chat_id)

        next_track = queue.advance()

        if next_track is None:
            await self.leave(chat_id)
            return

        try:
            await self._stream(
                chat_id,
                next_track,
            )

        except Exception:
            logger.exception(
                "Failed to play next track in chat %s",
                chat_id,
            )

            await self.leave(chat_id)

    async def add_and_play(
        self,
        chat_id: int,
        track: dict,
    ) -> str:
        """Add an audio track; play immediately if queue is idle."""

        queue = self.get_queue(chat_id)

        was_empty = queue.current() is None

        queue.add(track)

        if was_empty:
            try:
                await self._stream(
                    chat_id,
                    track,
                )

            except Exception:
                queue.clear()
                raise

            return "playing"

        return "queued"

    async def skip(self, chat_id: int):
        # Skipping cancels the current loop.
        self.loop_remaining.pop(chat_id, None)
        await self._play_next(chat_id)

    async def pause(self, chat_id: int):
        await self.pytgcalls.pause(chat_id)

    async def resume(self, chat_id: int):
        await self.pytgcalls.resume(chat_id)

    def set_loop(self, chat_id: int, count: int):
        self.loop_remaining[chat_id] = count

        logger.info(
            "Loop set to %s additional repeats in chat %s",
            count,
            chat_id,
        )

    def toggle_loop(self, chat_id: int) -> bool:
        """Toggle one additional repeat of the current track."""
        if self.get_loop_remaining(chat_id) > 0:
            self.disable_loop(chat_id)
            return False
        if self.get_queue(chat_id).current() is None:
            return False
        self.set_loop(chat_id, 1)
        return True

    def get_loop_remaining(self, chat_id: int) -> int:
        return self.loop_remaining.get(chat_id, 0)

    def disable_loop(self, chat_id: int):
        self.loop_remaining.pop(chat_id, None)

        logger.info(
            "Loop disabled in chat %s",
            chat_id,
        )

    async def leave(self, chat_id: int):
        self.queues.pop(chat_id, None)
        self.loop_remaining.pop(chat_id, None)

        try:
            await self.pytgcalls.leave_call(chat_id)

        except Exception as e:
            logger.debug(
                "leave_call for %s failed (probably already left): %s",
                chat_id,
                e,
            )


# IMPORTANT:
# Do not create Call(assistant) here.
# It must be created inside bot.py's running asyncio event loop.
call = None


def create_call(assistant_client):
    """
    Create the PyTgCalls instance from inside
    the application's running asyncio event loop.
    """
    global call

    if call is not None:
        return call

    call = Call(assistant_client)

    return call
