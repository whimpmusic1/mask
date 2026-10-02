from typing import Optional


class MusicQueue:
    """A tiny FIFO queue of tracks for one chat/voice call."""

    def __init__(self):
        self.tracks: list[dict] = []

    def add(self, track: dict) -> None:
        self.tracks.append(track)

    def current(self) -> Optional[dict]:
        return self.tracks[0] if self.tracks else None

    def advance(self) -> Optional[dict]:
        """Drop the finished/current track and return the new head, if any."""
        if self.tracks:
            self.tracks.pop(0)
        return self.current()

    def clear(self) -> None:
        self.tracks.clear()
