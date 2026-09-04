"""Visible, markup-safe held ordinary prompt widget for the Slo TUI."""

from __future__ import annotations

from src.tui.widgets.literal_text_static import LiteralTextStatic

__all__ = ["QueuedPromptBlock"]


class QueuedPromptBlock(LiteralTextStatic):
    """Render one ordinary prompt held behind the active agent run.

    WHAT: Shows literal user text with the ``⏳ Queued:`` prefix and supports
    in-place latest-wins replacement.
    WHO: ``SloTUI`` mounts it into ``#chat-shell`` directly above ``PromptInput``
    while its app-owned prompt slot is occupied — anchored outside the scroll
    region, never as a transcript entry.
    WHEN: It exists from a busy ordinary submission until run-finally drain or
    an explicit transcript/session clear. It owns no queue policy or task state.
    """

    DEFAULT_CSS = """
    QueuedPromptBlock {
        color: $text-muted;
        text-style: italic;
        padding: 0 1;
        margin: 0;
    }
    """

    def __init__(self, *, text: str) -> None:
        """Construct the visible held-prompt surface.

        WHAT: Renders the literal held text with the ``⏳ Queued:`` prefix.
        WHO: ``SloTUI._mount_queued_prompt_block`` creates it for a newly
        occupied queue slot.
        WHEN: The first ordinary busy submission fills the one-deep queue.

        Args:
            text (str): Ordinary prompt text held for the next run.
        """
        super().__init__()
        self._text: str = text
        self.update(f"⏳ Queued: {self._text}")

    @property
    def queued_text(self) -> str:
        """Return the text currently held by this visible queue block.

        WHAT: Exposes the literal prompt that the app will later submit.
        WHO: ``SloTUI`` reads it when validating the app-owned queue slot.
        WHEN: While the block is mounted, replaced, or drained.

        Returns:
            str: The newest held ordinary prompt text.
        """
        return self._text

    def replace_text(self, *, text: str) -> None:
        """Replace held text in place for a newer ordinary submission.

        WHAT: Updates this one presentation object rather than mounting another.
        WHO: ``SloTUI._queue_prompt`` calls it under the prompt-submission gate.
        WHEN: A user submits another ordinary prompt while a previous one is held.

        Args:
            text (str): Newest text that supersedes the prior held prompt.
        """
        self._text = text
        self.update(f"⏳ Queued: {self._text}")
