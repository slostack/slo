"""Sanitized operational failures at the native boundary."""


class ClaudeBridgeError(RuntimeError):
    """A fixed safe explanation; raw native exceptions must not cross this seam."""

    def __init__(self, *, code: str, safe_message: str) -> None:
        """Retain the safe failure code and bounded public guidance."""
        self.code: str = code
        super().__init__(safe_message[:300])

    @classmethod
    def protocol_error(cls) -> "ClaudeBridgeError":
        """Construct the fixed payload-free failure for malformed native responses.

        Returns:
            A new safe error; no native content or lifecycle state is retained.
        """
        return ClaudeBridgeError(
            code="stream_protocol_failed", safe_message="Malformed or unfinished Claude response."
        )


class ClaudeSubmissionNotStartedError(ClaudeBridgeError):
    """Proven no query attempt and settled cleanup; an explicit new attempt is safe."""

    def __init__(self, *, safe_message: str, code: str = "submission_not_started") -> None:
        """Keep the original safe category while marking explicit retry as safe."""
        super().__init__(code=code, safe_message=safe_message)
