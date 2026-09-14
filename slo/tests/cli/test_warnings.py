"""Tests for the CLI startup warning policy."""

from __future__ import annotations

import warnings

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

from src.cli.warnings import suppress_known_dependency_warnings


def test_suppresses_only_the_known_langgraph_cache_warning() -> None:
    """The startup filter hides the noisy dependency warning without muting others."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        suppress_known_dependency_warnings()
        warnings.warn(
            "The default value of `allowed_objects` will change in a future version. "
            "Pass an explicit value.",
            LangChainPendingDeprecationWarning,
        )
        warnings.warn(
            "another pending LangChain deprecation",
            LangChainPendingDeprecationWarning,
        )

    assert [str(warning.message) for warning in captured] == [
        "another pending LangChain deprecation",
    ]
