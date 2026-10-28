"""Bounded T2 projection privacy; not session publication or live Herdr acceptance."""

from pathlib import Path
from typing import Literal
from unittest.mock import patch
import json

from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO, HerdrRestoreCaptureDAO, HerdrRestoreConfigDAO
from src.agents.slo_agent.herdr.service import HerdrCliTransport
from tests.state_isolation import FakeHerdrFixture
from tests.agents.slo_agent.herdr.test_reporter import reporter, plain_slo

import pytest

from src.agents.slo_agent.herdr.dao import HerdrDisplayTokenDAO
from src.agents.slo_agent.sessions.dao import OperatorAttentionReason
from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO
from tests.agents.slo_agent.herdr.test_reporter import SESSION
from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO


@pytest.mark.parametrize(argnames="profile", argvalues=["compact", "detail"])
@pytest.mark.parametrize(argnames="history,available", argvalues=[(False, True), (True, False), (True, True)])
def test_zero_and_context_gates(
    profile: Literal["compact", "detail"], history: bool, available: bool
) -> None:
    """Known zero survives; context requires both history and an available estimate."""
    usage = SessionUsageSnapshotDAO(
        active_model_name="private",
        active_reasoning_level="off",
        usage_available=True,
        latest_turn=TokenUsageTotalsDAO(total_tokens=0, input_tokens=0, output_tokens=0),
        session_totals=TokenUsageTotalsDAO(
            total_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
        ),
        cooldown_seconds_remaining=0,
        requests_per_minute_limit=0,
        tokens_per_minute_limit=0,
        output_cap_tokens=0,
        provider_budget_tokens=0,
        context_window_snapshot=ContextWindowSnapshotDAO(
            model_name="private",
            estimate_available=available,
            context_window_tokens=0,
            estimated_used_tokens=0,
            available_tokens=0,
            consumed_percent=0.0,
        ),
    )
    result = HerdrSnapshotProjector.build(
        session_id=SESSION, state="idle", history_enabled=history, usage=usage, metadata_profile=profile
    )
    values: dict[str, str] = {token.key: token.value for token in result.tokens}
    assert "cooldown" not in values
    assert ("context" in values) is (history and available)
    if profile == "compact":
        assert values.get("session_tokens") == "0"
    else:
        assert all(
            values[key] == "0"
            for key in ("turn", "in", "out", "cache_read", "cache_write", "rpm", "tpm", "out_cap", "budget")
        )
        assert ("context_left" in values) is (history and available)


@pytest.mark.parametrize(
    argnames="level",
    argvalues=["off", "minimal", "low", "medium", "high", "xhigh", "max", "HIGH", " high", "private"],
)
def test_reasoning_exact_membership(level: str) -> None:
    """Only canonical constants survive, never normalization of arbitrary strings."""
    usage = SessionUsageSnapshotDAO(active_model_name="private", active_reasoning_level=level)
    result = HerdrSnapshotProjector.build(
        session_id=SESSION, state="idle", history_enabled=False, usage=usage, metadata_profile="detail"
    )
    assert [(token.key, token.value) for token in result.tokens] == (
        [("reasoning", level)] if level in ("off", "minimal", "low", "medium", "high", "xhigh", "max") else []
    )


@pytest.mark.parametrize(
    argnames="value,safe",
    argvalues=[
        ("x" * 80, True),
        ("x" * 81, False),
        ("é" * 64, True),
        ("é" * 65, False),
        ("", False),
        ("a b", True),
        ("a\tb", False),
        ("a\nb", False),
        ("a\rb", False),
        ("\x1b", False),
        ("\x7f", False),
        ("\u200b", False),
        ("\ue000", False),
        ("\u0378", False),
        ("\ud800", False),
        ("a\u00a0b", False),
        ("a\u2028b", False),
    ],
)
def test_final_token_boundary(value: str, safe: bool) -> None:
    """The projector and defensive DAO agree without normalizing or truncating."""
    token = HerdrSnapshotProjector._make_token(key="context", value=value)
    assert (token is not None) is safe
    if safe:
        assert token is not None and token.value == value
        assert HerdrDisplayTokenDAO(key="context", value=value).value == value
    else:
        with pytest.raises(ValueError):
            HerdrDisplayTokenDAO(key="context", value=value)


@pytest.mark.parametrize(
    argnames="value",
    argvalues=[None, True, False, -1, -0.5, float("nan"), float("inf"), -float("inf"), "private"],
)
def test_numeric_refusal(value: object) -> None:
    """Unknown, boolean, negative, nonfinite and text values never reach formatting."""
    assert not HerdrSnapshotProjector._finite(value=value)
    assert not HerdrSnapshotProjector._renderable(value=value)


@pytest.mark.parametrize(
    argnames="count,expected",
    argvalues=[
        (0, "0"),
        (999, "999"),
        (1000, "1.0k"),
        (9999, "10.0k"),
        (10000, "10k"),
        (12500, "13k"),
        (999999, "1000k"),
        (1000000, "1.0M"),
        (10000000, "10M"),
    ],
)
def test_projector_formatter_thresholds(count: int, expected: str) -> None:
    """Reporter uses the same documented half-up thresholds as the footer suite."""
    token = HerdrSnapshotProjector._number(key="session_tokens", value=count)
    assert token is not None and token.value == expected


@pytest.mark.parametrize(
    argnames="provider", argvalues=["ANTHROPIC", "OPENAI", "KIMI_FOR_CODING", "OPENROUTER"]
)
@pytest.mark.parametrize(argnames="profile", argvalues=["compact", "detail"])
async def test_four_provider_wire_privacy(
    fake_herdr: FakeHerdrFixture,
    tmp_path: Path,
    plain_slo: Path,
    caplog: pytest.LogCaptureFixture,
    provider: str,
    profile: Literal["compact", "detail"],
) -> None:
    """Actual child argv/environment and rejected output contain no private policy."""
    sentinel = f"synthetic-{provider}-private"
    fake_herdr.guard.require_registered(path=fake_herdr.executable)
    fake_herdr.executable.write_text(
        fake_herdr.executable.read_text() + f"\nassert {sentinel!r} not in str(dict(os.environ))\n"
        f"print({sentinel!r}); print({sentinel!r}, file=sys.stderr)\n"
        "if sys.argv[2] == 'report-metadata': sys.exit(9)\n"
    )
    owner = reporter(root=tmp_path)
    owner._transport = HerdrCliTransport(
        config=owner._config.model_copy(update={"binary_path": fake_herdr.executable}),
        environment={
            f"SLO_{provider}_API_KEY": sentinel,
            f"{provider}_API_KEY": sentinel,
            "PYTHONPATH": sentinel,
        },
    )
    tmp_path.chmod(0o700)
    owner._sequence_store.acquire()
    owner._lease_held = True
    try:
        with (
            patch.object(
                target=CredentialResolver,
                attribute="resolve",
                side_effect=AssertionError("credential lookup forbidden"),
            ) as resolve,
            patch.object(
                target=CredentialResolver,
                attribute="require",
                side_effect=AssertionError("credential lookup forbidden"),
            ) as require,
            patch.object(
                target=CredentialStore,
                attribute="load",
                side_effect=AssertionError("credential lookup forbidden"),
            ) as load,
        ):
            usage = SessionUsageSnapshotDAO(
                active_model_name=sentinel,
                active_reasoning_level=sentinel,
                provider_effort=sentinel,
                session_totals=TokenUsageTotalsDAO(total_tokens=12500),
            )
            snapshot = HerdrSnapshotProjector.build(
                session_id=SESSION, state="idle", history_enabled=False, usage=usage, metadata_profile=profile
            )
            capture = HerdrRestoreCaptureDAO(
                config=HerdrRestoreConfigDAO(
                    session_id=SESSION,
                    model_name=sentinel,
                    reasoning_level="off",
                    workdir=tmp_path / sentinel,
                    workspace_file=tmp_path / (sentinel + ".code-workspace"),
                    plugin_paths=(tmp_path / (sentinel + ".py"),),
                )
            )
            facts = HerdrPublicationDAO(
                configuration_generation=0, snapshot=snapshot, restore_capture=capture
            )
            owner.publish(publication=facts)
            await owner._consume_publication(publication=facts)
            assert owner._restore_ack is not None
            assert owner._display_ack_revision is None
            public = snapshot.model_dump_json() + repr(snapshot) + repr(facts) + repr(owner._saved)
            assert sentinel not in public
            resolve.assert_not_called()
            require.assert_not_called()
            load.assert_not_called()
    finally:
        await owner.close()
        await owner.close_transport()
    wire = fake_herdr.capture.read_text()
    commands = [json.loads(line) for line in wire.splitlines()]
    assert any("--herdr-restore" in command for command in commands)
    assert all("--agent-session-path" not in command for command in commands)
    assert sentinel not in wire + caplog.text
    sequence_files = tuple((tmp_path / "sequence-v1").glob("*.json"))
    assert sequence_files
    assert all(sentinel not in path.read_text() for path in sequence_files)
    assert "herdr_command_unavailable" in caplog.text
    assert not owner.retains_external_resources


@pytest.mark.parametrize(
    argnames="reason",
    argvalues=[
        "Authentication required",
        "Model preparation required",
        "Run failed; review Slo",
        "Approval required",
    ],
)
def test_fixed_block_reasons(reason: OperatorAttentionReason) -> None:
    """All four session-owned constants survive projection without arbitrary messages."""
    usage = SessionUsageSnapshotDAO(active_model_name="private", active_reasoning_level="off")
    result = HerdrSnapshotProjector.build(
        session_id=SESSION, state="blocked", block_reason=reason, history_enabled=False, usage=usage
    )
    assert result.block_reason == reason


@pytest.mark.parametrize(
    argnames="identity",
    argvalues=["private-slug", SESSION.upper().replace("00000001", "0000000A"), "{" + SESSION + "}"],
)
def test_invalid_identity_is_fixed_error(identity: str) -> None:
    """Herdr refuses noncanonical identities without echoing their input."""
    usage = SessionUsageSnapshotDAO(active_model_name="private", active_reasoning_level="off")
    with pytest.raises(ValueError, match="^Invalid Herdr identity\\.$") as error:
        HerdrSnapshotProjector.build(session_id=identity, state="idle", history_enabled=False, usage=usage)
    assert identity not in str(error.value)


@pytest.mark.parametrize(argnames="value", argvalues=[None, -1.0, float("nan"), float("inf")])
def test_invalid_context_is_independently_omitted(value: float | None) -> None:
    """A bad percentage does not discard known remaining tokens or other fields."""
    context = ContextWindowSnapshotDAO.model_construct(
        estimate_available=True, consumed_percent=value, available_tokens=0
    )
    usage = SessionUsageSnapshotDAO(
        active_model_name="private", active_reasoning_level="off", context_window_snapshot=context
    )
    result = HerdrSnapshotProjector.build(
        session_id=SESSION, state="idle", history_enabled=True, usage=usage, metadata_profile="detail"
    )
    assert [(token.key, token.value) for token in result.tokens] == [
        ("reasoning", "off"),
        ("context_left", "0 estimated"),
    ]


@pytest.mark.parametrize(argnames="cooldown", argvalues=[None, -1, 0, 1])
def test_compact_cooldown_cutoff(cooldown: int | None) -> None:
    """Nonpositive and unknown cooldowns disappear independently of known totals."""
    usage = SessionUsageSnapshotDAO(
        active_model_name="private",
        active_reasoning_level="off",
        cooldown_seconds_remaining=cooldown,
        session_totals=TokenUsageTotalsDAO(total_tokens=0),
    )
    result = HerdrSnapshotProjector.build(session_id=SESSION, state="idle", history_enabled=True, usage=usage)
    expected = [("session_tokens", "0")]
    if cooldown == 1:
        expected.append(("cooldown", "1s"))
    assert [(token.key, token.value) for token in result.tokens] == expected


def test_encoding_failure_omits_whole_token() -> None:
    """Exercise defensive encoding refusal, unreachable for ordinary non-C Python text."""

    class Unencodable(str):
        """Synthetic codec failure without logging the offending value."""

        def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
            """Raise the Unicode failure guarded by the shared predicate."""
            raise UnicodeError("synthetic codec failure")

    assert HerdrSnapshotProjector._make_token(key="context", value=Unencodable("1")) is None


def test_unavailable_turn_does_not_hide_session_totals() -> None:
    """Turn availability gates turn fields only, not independently known session counters."""
    usage = SessionUsageSnapshotDAO(
        active_model_name="private",
        active_reasoning_level="off",
        usage_available=False,
        latest_turn=TokenUsageTotalsDAO(total_tokens=9, input_tokens=8, output_tokens=1),
        session_totals=TokenUsageTotalsDAO(cache_read_input_tokens=0, cache_creation_input_tokens=-1),
    )
    result = HerdrSnapshotProjector.build(
        session_id=SESSION, state="idle", history_enabled=True, usage=usage, metadata_profile="detail"
    )
    assert [(token.key, token.value) for token in result.tokens] == [
        ("reasoning", "off"),
        ("cache_read", "0"),
    ]
