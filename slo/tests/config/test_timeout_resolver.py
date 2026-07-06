"""Tests for config/timeout_resolver.py.

Decision points covered:
- positive_float_env: primary set / alias fallback / default / invalid / non-positive
- optional_positive_float_env: absent / set valid / set invalid / set zero
- positive_int_env: primary set / alias fallback / default / invalid / non-positive

Spec 53.a.4 contract: invalid or non-positive env-var values must FALL BACK to
the default (or ``None`` for the optional helper) rather than raising, so a
malformed operator override never crashes the process at import time.
"""

from __future__ import annotations

import pytest

from config.timeout_resolver import (
    optional_positive_float_env,
    positive_float_env,
    positive_int_env,
)


# ---------------------------------------------------------------------------
# positive_float_env
# ---------------------------------------------------------------------------


class TestPositiveFloatEnv:
    def test_returns_primary_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_PRIMARY_TIMEOUT_SECONDS", "30.5")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            default=10.0,
        )
        assert result == pytest.approx(30.5)

    def test_falls_back_to_alias_when_primary_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_PRIMARY_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("SLO_ALIAS_TIMEOUT", "7.0")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            alias_name="SLO_ALIAS_TIMEOUT",
            default=10.0,
        )
        assert result == pytest.approx(7.0)

    def test_falls_back_to_alias_when_primary_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_PRIMARY_TIMEOUT_SECONDS", "   ")
        monkeypatch.setenv("SLO_ALIAS_TIMEOUT", "8.0")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            alias_name="SLO_ALIAS_TIMEOUT",
            default=10.0,
        )
        assert result == pytest.approx(8.0)

    def test_returns_default_when_neither_variable_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_PRIMARY_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("SLO_ALIAS_TIMEOUT", raising=False)
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            alias_name="SLO_ALIAS_TIMEOUT",
            default=15.0,
        )
        assert result == pytest.approx(15.0)

    def test_returns_default_when_no_alias_provided_and_primary_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_PRIMARY_TIMEOUT_SECONDS", raising=False)
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            default=5.0,
        )
        assert result == pytest.approx(5.0)

    def test_returns_default_for_non_numeric_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_PRIMARY_TIMEOUT_SECONDS", "not_a_number")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            default=10.0,
        )
        assert result == pytest.approx(10.0)

    def test_returns_default_for_zero_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_PRIMARY_TIMEOUT_SECONDS", "0")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            default=10.0,
        )
        assert result == pytest.approx(10.0)

    def test_returns_default_for_negative_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_PRIMARY_TIMEOUT_SECONDS", "-5.0")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            default=10.0,
        )
        assert result == pytest.approx(10.0)

    def test_primary_takes_precedence_over_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_PRIMARY_TIMEOUT_SECONDS", "20.0")
        monkeypatch.setenv("SLO_ALIAS_TIMEOUT", "99.0")
        result: float = positive_float_env(
            primary_name="SLO_PRIMARY_TIMEOUT_SECONDS",
            alias_name="SLO_ALIAS_TIMEOUT",
            default=10.0,
        )
        assert result == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# optional_positive_float_env
# ---------------------------------------------------------------------------


class TestOptionalPositiveFloatEnv:
    def test_returns_none_when_variable_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_OPT_TIMEOUT", raising=False)
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
        )
        assert result is None

    def test_returns_none_when_variable_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_OPT_TIMEOUT", "  ")
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
        )
        assert result is None

    def test_returns_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_OPT_TIMEOUT", "12.5")
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
        )
        assert result == pytest.approx(12.5)

    def test_falls_back_to_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLO_OPT_TIMEOUT", raising=False)
        monkeypatch.setenv("SLO_OPT_TIMEOUT_ALIAS", "3.0")
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
            alias_name="SLO_OPT_TIMEOUT_ALIAS",
        )
        assert result == pytest.approx(3.0)

    def test_returns_none_for_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_OPT_TIMEOUT", "0")
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
        )
        assert result is None

    def test_returns_none_for_non_numeric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_OPT_TIMEOUT", "abc")
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
        )
        assert result is None

    def test_returns_none_for_negative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_OPT_TIMEOUT", "-1.5")
        result: float | None = optional_positive_float_env(
            primary_name="SLO_OPT_TIMEOUT",
        )
        assert result is None


# ---------------------------------------------------------------------------
# positive_int_env
# ---------------------------------------------------------------------------


class TestPositiveIntEnv:
    def test_returns_primary_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_POOL_SIZE", "8")
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            default=4,
        )
        assert result == 8

    def test_falls_back_to_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLO_POOL_SIZE", raising=False)
        monkeypatch.setenv("SLO_POOL_SIZE_LEGACY", "3")
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            alias_name="SLO_POOL_SIZE_LEGACY",
            default=4,
        )
        assert result == 3

    def test_returns_default_when_neither_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_POOL_SIZE", raising=False)
        monkeypatch.delenv("SLO_POOL_SIZE_LEGACY", raising=False)
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            alias_name="SLO_POOL_SIZE_LEGACY",
            default=4,
        )
        assert result == 4

    def test_returns_default_for_non_integer_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_POOL_SIZE", "3.5")
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            default=4,
        )
        assert result == 4

    def test_returns_default_for_zero_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_POOL_SIZE", "0")
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            default=4,
        )
        assert result == 4

    def test_returns_default_for_negative_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_POOL_SIZE", "-1")
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            default=4,
        )
        assert result == 4

    def test_primary_takes_precedence_over_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_POOL_SIZE", "5")
        monkeypatch.setenv("SLO_POOL_SIZE_LEGACY", "99")
        result: int = positive_int_env(
            primary_name="SLO_POOL_SIZE",
            alias_name="SLO_POOL_SIZE_LEGACY",
            default=4,
        )
        assert result == 5
