"""A StringIO that records each ``write``/``flush`` call in order.

Bound as ``Console(file=...)`` so tests can assert the stream contract —
every printed line flushed — without a real terminal.
"""

import io


class RecordingStream(io.StringIO):
    """Logs ``"write"``/``"flush"`` events in call order."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    def write(self, s: str) -> int:
        """Record then delegate."""
        self.events.append("write")
        return super().write(s)

    def flush(self) -> None:
        """Record then delegate."""
        self.events.append("flush")
        return super().flush()
