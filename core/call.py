import asyncio
import logging
import time

import pyrogram.errors

# PyTgCalls 2.3.3 expects this older error name.
# Newer Pyrogram versions expose GroupCallForbidden instead.
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    if hasattr(pyrogram.errors, "GroupCallForbidden"):
        pyrogram.errors.GroupcallForbidden = pyrogram.errors.GroupCallForbidden

from pytgcalls import PyTgCalls
from pytgcalls import filters as fl
from pytgcalls.types import AudioQuality, MediaStream, StreamEnded

from core.queue import MusicQueue

logger = logging.getLogger(__name__)


class Call:
    """PyTgCalls wrapper with a per-chat FIFO audio queue."""

    def __init__(self, assistant_client):
        # Create this inside the running asyncio event loop.
        self.pytgcalls = PyTgCalls(assistant_client)
        self.queues: dict[int, MusicQueue] = {}
        self._leave_tasks: dict[int, asyncio.Task] = {}
        self._last_leave_at: dict[int, float] = {}
        self._leave_delay = 5.0
        self._join_cooldown = 1.5
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._manual_transition_at: dict[int, float] = {}
        self.loop_remaining: dict[int, int] = {}

        # Chats where we have a call connection that's already been
        # "kicked" into actually transmitting audio - see _stream() and
        # _warm_start_kick() for why this exists.
        self._active_chats: set[int] = set()

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
            logger.info("Stream-ended event received in chat %s", chat_id)

            async with self._chat_lock(chat_id):
                changed_at = self._manual_transition_at.get(chat_id, 0.0)
                elapsed = time.monotonic() - changed_at
                if elapsed < 2.5:
                    logger.info(
                        "Ignoring possible stale stream-end event in chat %s "
                        "(%.2fs after manual transition)",
                        chat_id,
                        elapsed,
                    )
                    return
                await self._handle_stream_end(chat_id)

    async def _handle_stream_end(self, chat_id: int):
        queue = self.get_queue(chat_id)
        current = queue.current()
        logger.info(
            "Handling stream end in chat %s; current=%r queue_size=%d",
            chat_id,
            current.get("title") if current else None,
            len(queue.tracks),
        )

        remaining = self.loop_remaining.get(chat_id, 0)
        if remaining > 0 and current is not None:
            self.loop_remaining[chat_id] = remaining - 1
            logger.info(
                "Looping current track in chat %s; repeats remaining=%d",
                chat_id,
                remaining - 1,
            )
            try:
                await self._stream(chat_id, current)
            except Exception:
                logger.exception("Failed to loop current track in chat %s", chat_id)
                await self._leave_locked(chat_id)
            return

        self.loop_remaining.pop(chat_id, None)
        await self._play_next(chat_id)

    def _build_stream(self, track: dict) -> MediaStream:
        """Build a PyTgCalls stream from the downloader's track dictionary."""
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
                logger.info("Waiting %.2fs before rejoining chat %s", remaining, chat_id)
                await asyncio.sleep(remaining)
            self._last_leave_at.pop(chat_id, None)

    async def _stream(self, chat_id: int, track: dict):
        """Start a stream, reusing a call if teardown is pending."""
        self._cancel_pending_leave(chat_id)
        await self._wait_for_join_cooldown(chat_id)
        logger.info(
            "Building stream in chat %s: title=%r duration=%r url_present=%s headers_present=%s",
            chat_id,
            track.get("title"),
            track.get("duration"),
            bool(track.get("url")),
            bool(track.get("http_headers")),
        )
        stream = self._build_stream(track)

        # True only the first time we're joining this chat's call fresh -
        # not on a track switch within an already-active call (those
        # already work fine with no extra kick needed).
        is_fresh_join = chat_id not in self._active_chats

        try:
            await self.pytgcalls.play(chat_id, stream)
            logger.info(
                "PyTgCalls play() returned in chat %s for %r",
                chat_id,
                track.get("title"),
            )
        except Exception:
            logger.exception(
                "PyTgCalls play() failed in chat %s for %r",
                chat_id,
                track.get("title"),
            )
            raise

        self._active_chats.add(chat_id)

    # Delays (seconds, between successive attempts) for the warm-start
    # re-kick below. One attempt at 2s turned out not to be reliable
    # enough in practice, so this retries a few times over the first
    # ~10 seconds instead of giving up after a single try.
    _WARM_START_DELAYS = (1.0, 3.0, 6.0)

    async def _warm_start_kick(self, chat_id: int, track: dict, stream: MediaStream):
        """
        Diagnosed from: /play joins the call and the UI shows "Now
        playing", but no audio comes out - for several minutes, well
        past the track's own duration - until a /skip switches to a
        different track, at which point the *tail end* of the first
        track is briefly audible before the new one plays normally.
        That specific symptom (audio exists, just isn't being
        transmitted, and a stream re-trigger releases it) matches a
        known PyTgCalls quirk: a brand-new join can report success
        immediately while the underlying transport hasn't actually
        started sending yet. skip() was accidentally "fixing" this by
        re-issuing play() - this does the same thing automatically,
        at a few points after every fresh join, instead of requiring a
        manual skip to unstick it.

        If audio is STILL silent on first play after this, the logs
        from this method (search for "Warm-start" in Railway's logs)
        will show whether these re-kicks are even firing/succeeding -
        that's the next real diagnostic signal needed, since this
        behavior depends on PyTgCalls/Telegram internals that can't be
        verified without a live call to test against.
        """
        for attempt, delay in enumerate(self._WARM_START_DELAYS, start=1):
            await asyncio.sleep(delay)

            queue = self.queues.get(chat_id)
            if queue is None or queue.current() is not track:
                logger.info(
                    "Warm-start attempt %d/%d for chat %s skipped - "
                    "track changed already.",
                    attempt, len(self._WARM_START_DELAYS), chat_id,
                )
                return

            logger.info(
                "Warm-start attempt %d/%d: re-kicking stream in chat %s",
                attempt, len(self._WARM_START_DELAYS), chat_id,
            )
            try:
                await self.pytgcalls.play(chat_id, stream)
                logger.info(
                    "Warm-start attempt %d/%d succeeded in chat %s",
                    attempt, len(self._WARM_START_DELAYS), chat_id,
                )
            except Exception:
                logger.exception(
                    "Warm-start attempt %d/%d failed in chat %s",
                    attempt, len(self._WARM_START_DELAYS), chat_id,
                )

    async def _play_next(self, chat_id: int):
        queue = self.get_queue(chat_id)
        logger.info("Advancing queue in chat %s; size_before=%d", chat_id, len(queue.tracks))
        next_track = queue.advance()
        logger.info(
            "Queue advanced in chat %s; next=%r size_after=%d",
            chat_id,
            next_track.get("title") if next_track else None,
            len(queue.tracks),
        )

        if next_track is None:
            await self._update_player(chat_id, None)
            self._schedule_leave(chat_id)
            return None

        try:
            await self._stream(chat_id, next_track)
            await self._update_player(chat_id, next_track)
        except Exception:
            logger.exception("Failed to play next track in chat %s", chat_id)
            await self._leave_locked(chat_id)
            return None

        return next_track

    async def add_and_play(self, chat_id: int, track: dict) -> str:
        """Queue a track and start it if the queue is idle."""
        async with self._chat_lock(chat_id):
            self._cancel_pending_leave(chat_id)
            queue = self.get_queue(chat_id)
            was_empty = queue.current() is None
            queue.add(track)
            logger.info(
                "Track added in chat %s: title=%r was_empty=%s queue_size=%d",
                chat_id,
                track.get("title"),
                was_empty,
                len(queue.tracks),
            )
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
        """Returns the new current track, or None if the queue is now empty."""
        async with self._chat_lock(chat_id):
            self.loop_remaining.pop(chat_id, None)
            self._manual_transition_at[chat_id] = time.monotonic()
            logger.info("Manual skip in chat %s", chat_id)
            return await self._play_next(chat_id)

    async def pause(self, chat_id: int):
        await self.pytgcalls.pause(chat_id)

    async def resume(self, chat_id: int):
        await self.pytgcalls.resume(chat_id)

    def set_loop(self, chat_id: int, count: int):
        self.loop_remaining[chat_id] = count
        logger.info("Loop set to %s additional repeats in chat %s", count, chat_id)

    def toggle_loop(self, chat_id: int) -> bool:
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
        logger.info("Loop disabled in chat %s", chat_id)

    async def _update_player(self, chat_id: int, track):
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
        self._active_chats.discard(chat_id)
        try:
            await self.pytgcalls.leave_call(chat_id)
            self._last_leave_at[chat_id] = time.monotonic()
        except Exception as exc:
            logger.debug("leave_call for %s failed (probably already left): %s", chat_id, exc)


# Do not create Call(assistant) at import time. Create it inside bot.py's
# running asyncio event loop.
call = None


def create_call(assistant_client):
    """Create the PyTgCalls instance inside the application's event loop."""
    global call
    if call is not None:
        return call
    call = Call(assistant_client)
    return call
