"""Agent-loop hooks: caller-supplied policy callbacks invoked by ``SloAgent``.

See ``hook.py`` for the ``Hook`` namespace class, the hook context
DAOs, and the canonical hook type aliases.
"""
from __future__ import annotations

from src.agents.hooks.hook import (
    Hook,
    ShouldStopAfterTurnHook,
    ShouldStopAfterTurnHookContextDAO,
    TurnAccumulatorDAO,
)


__all__ = [
    "Hook",
    "ShouldStopAfterTurnHook",
    "ShouldStopAfterTurnHookContextDAO",
    "TurnAccumulatorDAO",
]
