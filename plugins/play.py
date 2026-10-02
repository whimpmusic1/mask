import logging

import pyrogram.errors

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
    def __init__(self, assistant_client):
        self.pytgcalls = PyTgCalls(assistant_client)

        self.queues: dict[int, MusicQueue] = {}

        # Loop state for each group.
        self.loop_enabled: dict[int, bool] = {}

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

            # If loop is enabled, replay the current track.
            if self.loop_enabled.get(chat_id, False):
                current = self.get_queue(chat_id).current()

                if current is not None:
                    logger.info(
                        "Loop enabled in chat %s - replaying: %s",
                        chat_id,
                        current["title"],
                    )

                    try:
                        await self._stream(chat_id, current)
                    except Exception:
                        logger.exception(
                            "Failed to replay looped track in chat %s",
                            chat_id,
                        )
                        await self.leave(chat_id)

                    return

            # Normal behavior: move to the next track.
            await self._play_next(chat_id)

    def _build_stream(self, url: str) -> MediaStream:
        return MediaStream(
            url,
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.IGNORE,
        )

    async def _stream(self, chat_id: int, track: dict):
        stream = self._build_stream(track["url"])

        try:
            await self.pytgcalls.play(chat_id, stream)

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
            await self._stream(chat_id, next_track)

        except Exception:
            logger.exception(
                "Failed to play next track in chat %s",
                chat_id,
            )
            await self.leave(chat_id)

    async def add_and_play(self, chat_id: int, track: dict) -> str:
        queue = self.get_queue(chat_id)

        was_empty = queue.current() is None

        queue.add(track)

        if was_empty:
            try:
                await self._stream(chat_id, track)

            except Exception:
                queue.clear()
                raise

            return "playing"

        return "queued"

    async def skip(self, chat_id: int):
        await self._play_next(chat_id)

    async def pause(self, chat_id: int):
        await self.pytgcalls.pause(chat_id)

    async def resume(self, chat_id: int):
        await self.pytgcalls.resume(chat_id)

    def is_loop_enabled(self, chat_id: int) -> bool:
        return self.loop_enabled.get(chat_id, False)

    def toggle_loop(self, chat_id: int) -> bool:
        enabled = not self.loop_enabled.get(chat_id, False)

        self.loop_enabled[chat_id] = enabled

        logger.info(
            "Loop %s in chat %s",
            "enabled" if enabled else "disabled",
            chat_id,
        )

        return enabled

    async def leave(self, chat_id: int):
        self.queues.pop(chat_id, None)

        # Remove loop state when leaving the voice chat.
        self.loop_enabled.pop(chat_id, None)

        try:
            await self.pytgcalls.leave_call(chat_id)

        except Exception as e:
            logger.debug(
                "leave_call for %s failed (probably already left): %s",
                chat_id,
                e,
            )


call = None


def create_call(assistant_client):
    global call

    if call is not None:
        return call

    call = Call(assistant_client)

    return call
