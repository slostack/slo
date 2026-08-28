"""Targeted third-party warning policy for Slo CLI startup."""
from __future__ import annotations

import warnings

__all__ = ["suppress_known_dependency_warnings"]


_LANGGRAPH_ALLOWED_OBJECTS_WARNING: str = (
    r"The default value of `allowed_objects` will change in a future version\."
)


def suppress_known_dependency_warnings() -> None:
    """Hide known dependency warnings that Slo cannot configure directly.

    LangGraph currently constructs its default cache serializer during import,
    without exposing the serializer's ``allowed_objects`` setting to Slo. The
    dependency emits a pending-deprecation warning on every CLI launch as a
    result. Suppress only that known warning; all unrelated warnings remain
    visible.
    """
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

    warnings.filterwarnings(
        "ignore",
        message=_LANGGRAPH_ALLOWED_OBJECTS_WARNING,
        category=LangChainPendingDeprecationWarning,
    )
