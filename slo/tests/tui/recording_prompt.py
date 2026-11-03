"""Test-owned outcome observation injected through the host's prompt factory."""

from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.prompt_input.commands import PromptCommand
from src.tui.components.prompt_input.submission import SubmissionOutcomeDAO


class RecordingPromptInput(PromptInputComponent):
    """Keep assertion evidence only in tests, never in a production editor."""

    def __init__(self) -> None:
        """Construct the real editor with a test-lifetime receipt record."""
        super().__init__()
        self.outcomes: list[SubmissionOutcomeDAO] = []
        self.failures_remaining: int = 0

    async def handle(self, *, command: PromptCommand) -> None:
        """Record delivery and optionally fail before real adoption for join tests."""
        if isinstance(command, SubmissionOutcomeDAO):
            self.outcomes.append(command)
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise RuntimeError("injected outcome failure")
        await super().handle(command=command)
