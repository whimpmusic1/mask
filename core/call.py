import logging

import pyrogram.errors

# PyTgCalls 2.3.3 expects this older error name.
# Newer Pyrogram versions expose GroupCallForbidden instead.
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    if hasattr(pyrogram.errors, "GroupCallForbidden"):
        pyrogram.errors.GroupcallForbidden = (
            pyrogram.errors.GroupCallForbidden
        )

import asyncio
import time

from pytgcalls import PyTgCalls
from pytgcalls import filters as fl
from pytgcalls.types import AudioQuality, MediaStream, StreamEnded

from core.queue import MusicQueue

logger = logging.getLogger(__name__)

# After actually leaving a call, wait at least this long before rejoining -
# rejoining too fast after a real leave is what causes "joined but no
# audio" (see _stream below for the full explanation).
_MIN_REJOIN_GAP_SECONDS = 1.5

# Don't leave the call the instant the queue empties - give this long for
# a follow-up /play to show up first, so back-to-back play/skip/play never
# has to actually leave+rejoin at all (see _play_next).
_EMPTY_QUEUE_GRACE_SECONDS = 5


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

        # chat_id -> asyncio.Task for a scheduled "actually leave now"
        # once the queue has been empty for _EMPTY_QUEUE_GRACE_SECONDS.
        self._pending_leave: dict[int, asyncio.Task] = {}

        # chat_id -> time.monotonic() of the last real leave_call(), used
        # to enforce _MIN_REJOIN_GAP_SECONDS before joining again.
        self._last_left_at: dict[int, float] = {}

        # Optional async callback: on_track_change(chat_id, track_or_None).
        # Set from bot.py once plugins are loaded, so the UI (the player
        # message in plugins/controls.py) can stay in sync with *every*
        # path that changes what's playing - initial play, skip, a track
        # ending naturally, or the queue running out. Kept as a plain
        # settable attribute (not an import) specifically to avoid any
        # import cycle between core.call and plugins.controls.
        self.on_track_change = None

        self._register_handlers()

    async def _notify_track_change(self, chat_id: int, track):
        if self.on_track_change is None:
            return
        try:
            await self.on_track_change(chat_id, track)
        except Exception:
            logger.exception(
                "on_track_change hook failed for chat %s", chat_id
            )

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

    def _cancel_pending_leave(self, chat_id: int) -> None:
        task = self._pending_leave.pop(chat_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _delayed_leave(self, chat_id: int) -> None:
        try:
            await asyncio.sleep(_EMPTY_QUEUE_GRACE_SECONDS)
        except asyncio.CancelledError:
            # A new track showed up in time (add_and_play cancelled us) -
            # the call is still active and already playing it, nothing to do.
            return

        queue = self.queues.get(chat_id)
        if queue is None or queue.current() is None:
            logger.info(
                "Queue in %s still empty after grace period - leaving.",
                chat_id,
            )
            await self._do_leave(chat_id)

        self._pending_leave.pop(chat_id, None)

    async def _do_leave(self, chat_id: int) -> None:
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
        finally:
            self._last_left_at[chat_id] = time.monotonic()

    async def _stream(self, chat_id: int, track: dict):
        """
        Start an audio stream, auto-creating the voice chat if needed.

        Important: if we actually left this chat's call recently, wait
        out a short minimum gap before rejoining. Rejoining a Telegram
        voice chat immediately after leaving it can race with the
        server/pytgcalls still tearing down the previous session -
        pytgcalls reports the join as successful and nothing raises, but
        no audio ever actually flows. This is exactly what was causing
        "play -> skip -> play" to go silent: skip emptied the queue,
        which used to leave the call immediately, and the very next
        /play rejoined too fast. Giving the queue a short grace period
        before actually leaving (see _play_next/add_and_play) avoids
        the leave+rejoin cycle entirely for the common case; this gap
        is the backstop for whenever a real leave did happen.
        """
        last_left = self._last_left_at.get(chat_id)
        if last_left is not None:
            elapsed = time.monotonic() - last_left
            if elapsed < _MIN_REJOIN_GAP_SECONDS:
                await asyncio.sleep(_MIN_REJOIN_GAP_SECONDS - elapsed)

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
            # Don't leave immediately - see _delayed_leave's docstring
            # and _stream's: this is the fix for play -> skip -> play
            # going silent.
            self._cancel_pending_leave(chat_id)
            self._pending_leave[chat_id] = asyncio.create_task(
                self._delayed_leave(chat_id)
            )
            await self._notify_track_change(chat_id, None)
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

            await self._do_leave(chat_id)
            await self._notify_track_change(chat_id, None)
            return

        await self._notify_track_change(chat_id, next_track)

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
            # A follow-up /play showed up inside the grace period - cancel
            # the scheduled leave so we never actually drop the call, and
            # pytgcalls.play() below just switches the stream smoothly.
            self._cancel_pending_leave(chat_id)

            try:
                await self._stream(
                    chat_id,
                    track,
                )

            except Exception:
                queue.clear()
                raise

            await self._notify_track_change(chat_id, track)
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
        """Manual /stop - leaves immediately, no grace period."""
        self._cancel_pending_leave(chat_id)
        await self._do_leave(chat_id)
        await self._notify_track_change(chat_id, None)


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
