"""Pure display boundary tests (projector implementation belongs to T2)."""

import pytest
from src.agents.slo_agent.herdr import dao


@pytest.mark.parametrize("value", ["x" * 80, "é" * 64, "1.0k", "Approval required"])
def test_token_accepts_safe_boundary(value: str) -> None:
    """Character and byte bounds are independent."""
    assert dao.HerdrDisplayTokenDAO.model_validate({"key": "context", "value": value}).value == value


@pytest.mark.parametrize("value", ["", "x" * 81, "é" * 65, "a\nb", "\x1b", "\u200b", "\ud800", "a\tb"])
def test_token_refuses_unsafe_boundary(value: str) -> None:
    """Reject whole invalid tokens without echoing values."""
    with pytest.raises(ValueError):
        dao.HerdrDisplayTokenDAO.model_validate({"key": "context", "value": value})


@pytest.mark.parametrize(argnames="value", argvalues=["", "x" * 80, "x" * 81, "é" * 64, "é" * 65, "\ud800"])
def test_shared_safe_token_predicate(value: str) -> None:
    """Projector and DAO consume one nonthrowing final boundary."""
    expected = (
        bool(value) and len(value) <= 80 and value != "\ud800" and len(value.encode(errors="replace")) <= 128
    )
    assert dao.HerdrDisplayTokenDAO._safe_token_value(value=value) is expected


def test_compact_projector_omits_all_free_text() -> None:
    """Only numeric telemetry survives secret-bearing model and effort fields."""
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
    from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO

    usage = SessionUsageSnapshotDAO(
        active_model_name="private-sentinel",
        active_reasoning_level="high",
        provider_effort="private-sentinel",
        session_totals=TokenUsageTotalsDAO(total_tokens=12500),
        cooldown_seconds_remaining=3,
    )
    result = HerdrSnapshotProjector.build(
        session_id="12345678-1234-1234-1234-123456789abc",
        state="idle",
        history_enabled=False,
        usage=usage,
        metadata_profile="compact",
    )
    assert [(t.key, t.value) for t in result.tokens] == [("session_tokens", "13k"), ("cooldown", "3s")]
    assert "private-sentinel" not in result.model_dump_json()


@pytest.mark.parametrize(argnames="history", argvalues=[False, True])
def test_detail_numeric_projection(history: bool) -> None:
    """Detail uses ordered known telemetry, fixed reasoning and history-gated estimates."""
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
    from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO
    from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO

    usage = SessionUsageSnapshotDAO(
        active_model_name="secret",
        active_reasoning_level="high",
        usage_available=True,
        latest_turn=TokenUsageTotalsDAO(total_tokens=1000, input_tokens=0, output_tokens=999),
        session_totals=TokenUsageTotalsDAO(cache_read_input_tokens=2000, cache_creation_input_tokens=3000),
        requests_per_minute_limit=500,
        tokens_per_minute_limit=10000,
        output_cap_tokens=8000,
        provider_budget_tokens=4000,
        context_window_snapshot=ContextWindowSnapshotDAO(
            model_name="secret",
            context_window_tokens=10000,
            estimated_used_tokens=2500,
            available_tokens=7500,
            consumed_percent=25.0,
            estimate_available=True,
        ),
    )
    result = HerdrSnapshotProjector.build(
        session_id="12345678-1234-1234-1234-123456789abc",
        state="idle",
        history_enabled=history,
        usage=usage,
        metadata_profile="detail",
    )
    expected = [
        ("reasoning", "high"),
        ("turn", "1.0k"),
        ("in", "0"),
        ("out", "999"),
        ("cache_read", "2.0k"),
        ("cache_write", "3.0k"),
    ]
    if history:
        expected += [("context_left", "7.5k estimated")]
    expected += [("rpm", "500"), ("tpm", "10k"), ("out_cap", "8.0k"), ("budget", "4.0k")]
    if history:
        expected += [("context", "25.0% estimated")]
    assert [(t.key, t.value) for t in result.tokens] == expected


def test_compact_context_precedes_cooldown() -> None:
    """Public compact fields retain the specified inventory order."""
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
    from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
    from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO

    usage = SessionUsageSnapshotDAO(
        active_model_name="private",
        active_reasoning_level="off",
        cooldown_seconds_remaining=3,
        context_window_snapshot=ContextWindowSnapshotDAO(
            model_name="private",
            context_window_tokens=100,
            estimated_used_tokens=25,
            available_tokens=75,
            consumed_percent=25.0,
            estimate_available=True,
        ),
    )
    result = HerdrSnapshotProjector.build(
        session_id="12345678-1234-1234-1234-123456789abc",
        state="idle",
        history_enabled=True,
        usage=usage,
    )
    assert [(token.key, token.value) for token in result.tokens] == [("context", "25.0%"), ("cooldown", "3s")]


@pytest.mark.parametrize(
    argnames="value", argvalues=[10**400, 10**5000], ids=["float-overflow", "decimal-limit"]
)
def test_oversized_count_is_omitted_without_float_conversion(value: int) -> None:
    """Unrenderable integers cannot abort the entire public projection."""
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector

    assert HerdrSnapshotProjector._number(key="session_tokens", value=value) is None


@pytest.mark.parametrize(argnames="field", argvalues=["rpm", "cooldown", "context", "context_left"])
@pytest.mark.parametrize(
    argnames="value", argvalues=[10**400, 10**5000], ids=["float-overflow", "decimal-limit"]
)
def test_huge_numeric_fields_do_not_abort_projection(field: str, value: int) -> None:
    """Every generated numeric field omits unrenderable values independently."""
    from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
    from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
    from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO

    context = ContextWindowSnapshotDAO.model_construct(
        estimate_available=True,
        available_tokens=value if field == "context_left" else None,
        consumed_percent=value if field == "context" else None,
    )
    usage = SessionUsageSnapshotDAO(
        active_model_name="private",
        active_reasoning_level="high",
    ).model_copy(
        update={
            "requests_per_minute_limit": value if field == "rpm" else None,
            "cooldown_seconds_remaining": value if field == "cooldown" else None,
            "context_window_snapshot": context,
        }
    )
    result = HerdrSnapshotProjector.build(
        session_id="12345678-1234-1234-1234-123456789abc",
        state="idle",
        history_enabled=True,
        usage=usage,
        metadata_profile="compact" if field == "cooldown" else "detail",
    )
    assert field not in [token.key for token in result.tokens]


def test_snapshot_has_no_private_policy() -> None:
    """Public shape is closed and token keys are unique."""
    token = dao.HerdrDisplayTokenDAO.model_validate({"key": "context", "value": "1%"})
    assert dao.HerdrReportSnapshotDAO.model_validate(
        {"session_id": "s", "state": "idle", "tokens": [token]}
    ).tokens == (token,)
    with pytest.raises(ValueError):
        dao.HerdrReportSnapshotDAO.model_validate(
            {"session_id": "s", "state": "idle", "tokens": [token, token]}
        )
    with pytest.raises(ValueError):
        dao.HerdrReportSnapshotDAO.model_validate(
            {"session_id": "s", "state": "idle", "tokens": [], "restore_capture": "secret"}
        )
