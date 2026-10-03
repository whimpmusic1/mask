import asyncio
import logging
import time

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
        # Delay teardown after the last track so an immediate /play can reuse
        # the active Telegram voice-chat connection.
        self._leave_tasks: dict[int, asyncio.Task] = {}
        self._last_leave_at: dict[int, float] = {}
        self._leave_delay = 5.0
        self._join_cooldown = 1.5
        # Serialize play/skip/end transitions per chat. A short suppression
        # window prevents a replaced stream's delayed end event from skipping
        # the newly-started track a second time.
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._manual_transition_at: dict[int, float] = {}

        # Number of additional times the current song should repeat.
        # Example:
        # /loop 5 -> current song repeats 5 additional times.
        self.loop_remaining: dict[int, int] = {}

        self._register_handlers()

    def _chat_lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

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

            async with self._chat_lock(chat_id):
                # play() may emit the replaced stream's end event shortly after
                # an explicit skip. Do not advance the queue twice.
                changed_at = self._manual_transition_at.get(chat_id, 0.0)
                if time.monotonic() - changed_at < 2.5:
                    logger.info("Ignoring stale stream-end during transition in chat %s", chat_id)
                    return

                await self._handle_stream_end(chat_id)

    async def _handle_stream_end(self, chat_id: int):
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
                    await self._leave_locked(chat_id)

                return

        # Normal queue behaviour.
        self.loop_remaining.pop(chat_id, None)

        await self._play_next(chat_id)


    def _build_stream(self, track: dict) -> MediaStream:
        headers = track.get("http_headers") or {}
        
        return MediaStream(
            track["url"],
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.IGNORE,
            headers=headers,
        )

    async def start(self):
        await self.pytgcalls.start()

    def _cancel_pending_leave(self, chat_id: int) -> None:
        task = self._leave_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _wait_for_join_cooldown(self, chat_id: int) -> None:
        left_at = self._last_leave_at.get(chat_id)
        if left_at is not None:
            remaining = self._join_cooldown - (time.monotonic() - left_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_leave_at.pop(chat_id, None)

    async def _stream(self, chat_id: int, track: dict):
        """Start an audio stream, reusing a call if teardown is pending."""
        self._cancel_pending_leave(chat_id)
        await self._wait_for_join_cooldown(chat_id)
        stream = self._build_stream(track)

        logger.info(
            "Starting stream in chat %s: title=%r, duration=%s, headers_present=%s",
            chat_id,
            track.get("title"),
            track.get("duration"),
            bool(track.get("http_headers")),
        )

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
            await self._update_player(chat_id, None)
            self._schedule_leave(chat_id)
            return

        try:
            await self._stream(
                chat_id,
                next_track,
            )
            await self._update_player(chat_id, next_track)

        except Exception:
            logger.exception(
                "Failed to play next track in chat %s",
                chat_id,
            )

            await self._leave_locked(chat_id)

    async def add_and_play(self, chat_id: int, track: dict) -> str:
        """Add a track and start it if this chat's queue is idle."""
        async with self._chat_lock(chat_id):
            self._cancel_pending_leave(chat_id)
            queue = self.get_queue(chat_id)
            was_empty = queue.current() is None
            queue.add(track)
            if was_empty:
                try:
                    await self._stream(chat_id, track)
                except Exception:
                    queue.clear()
                    raise
                await self._update_player(chat_id, track)
                return "playing"
            return "queued"

    async def skip(self, chat_id: int):
        async with self._chat_lock(chat_id):
            self.loop_remaining.pop(chat_id, None)
            self._manual_transition_at[chat_id] = time.monotonic()
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

    async def _update_player(self, chat_id: int, track):
        # Local import avoids the core.call <-> plugins.controls import cycle.
        try:
            from plugins.controls import _update_now_playing_message
            await _update_now_playing_message(chat_id, track)
        except Exception:
            logger.exception("Failed to update player message in chat %s", chat_id)

    def _schedule_leave(self, chat_id: int) -> None:
        self._cancel_pending_leave(chat_id)

        async def delayed_leave():
            try:
                await asyncio.sleep(self._leave_delay)
                # A new track may have arrived while this task was sleeping.
                if self.get_queue(chat_id).current() is None:
                    await self._leave_locked(chat_id)
            except asyncio.CancelledError:
                pass
            finally:
                if self._leave_tasks.get(chat_id) is asyncio.current_task():
                    self._leave_tasks.pop(chat_id, None)

        self._leave_tasks[chat_id] = asyncio.create_task(delayed_leave())

    async def leave(self, chat_id: int):
        async with self._chat_lock(chat_id):
            await self._leave_locked(chat_id)

    async def _leave_locked(self, chat_id: int):
        self._cancel_pending_leave(chat_id)
        await self._update_player(chat_id, None)
        self.queues.pop(chat_id, None)
        self.loop_remaining.pop(chat_id, None)
        try:
            await self.pytgcalls.leave_call(chat_id)
            self._last_leave_at[chat_id] = time.monotonic()
        except Exception as e:
            logger.debug("leave_call for %s failed (probably already left): %s", chat_id, e)


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
