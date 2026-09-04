"""Conservative shared process-liveness probing.

Sub-spec 71.a.0.
"""

from __future__ import annotations

import os

__all__ = ["ProcessProbe"]


class ProcessProbe:
    """Answer whether a process exists without false dead verdicts."""

    @classmethod
    def is_alive(cls, *, pid: int) -> bool:
        """Return whether a positive process identifier is still live.

        WHAT: Performs a zero-signal probe; only ProcessLookupError proves the
            process is gone, while permission and other OS errors stay live.
        WHO: Called by workflow reconciliation and future child reapers.
        WHEN: When liveness evidence is needed as a last-resort signal.

        Args:
            pid (int): Candidate process identifier.

        Returns:
            bool: False for non-positive identifiers or a missing process.
        """
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True
