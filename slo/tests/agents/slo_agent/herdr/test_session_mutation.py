"""Ordinary commits must not authorize unrelated mutable restore policy."""

from unittest.mock import patch
from collections.abc import Iterator

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.base import LLMBuildResult, LLMFactory
from src.agents.providers.faux import FauxChatModel

from pathlib import Path

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.herdr.test_session_capture import configured_pool


@pytest.fixture(autouse=True)
def faux_factory() -> Iterator[None]:
    """Bind the safe factory before constructing any config-backed session."""
    with patch.object(
        LLMFactory,
        "create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="done")]),
            supports_explicit_caching=False,
        ),
    ):
        yield


@pytest.mark.parametrize("mutation", ["reasoning", "history", "pool"])
async def test_reasoning_commit_does_not_certify_unrelated_policy(tmp_path: Path, mutation: str) -> None:
    """An intended effective-reasoning change cannot bless a caller's other edits."""
    config = SessionConfigDAO(workdir=tmp_path, model_pool_dao=configured_pool(), reasoning_level="low")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    previous = session._herdr_capture
    assert previous is not None
    if mutation == "reasoning":
        config.reasoning_level = "medium"
    elif mutation == "history":
        config.enable_history = False
    else:
        assert config.model_pool_dao is not None
        config.model_pool_dao.entries[0].cooldown_seconds = 99
    session.switch_reasoning_level(reasoning_level="high")
    assert session._herdr_capture is None
    await session.rename_session(session_name="still ineligible")
    assert session._herdr_capture is None
    assert previous.config.reasoning_level == "low"


@pytest.mark.parametrize("boundary", ["history", "activation", "bootstrap"])
async def test_restoring_mutated_value_does_not_restore_trust(tmp_path: Path, boundary: str) -> None:
    """Once observed, unsupported changes cannot escape via later ordinary recapture."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    config.reasoning_level = "high"
    session._withdraw_stale_herdr_capture()
    assert session._herdr_capture is None
    config.reasoning_level = "low"
    if boundary == "history":
        await session.rename_session(session_name="restored")
    elif boundary == "activation":
        await session._prepare_herdr_capture_inputs(interactive=True)
    else:
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._herdr_capture is None


@pytest.mark.parametrize("value", [False, 1, "true", None])
async def test_malformed_history_policy_is_not_certified(tmp_path: Path, value: object) -> None:
    """Capture refuses malformed source policy rather than coercing it to truth."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    config.__dict__["enable_history"] = value
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is None


async def test_bootstrap_cannot_certify_mutation_during_construction(tmp_path: Path) -> None:
    """Permission precedes construction and cannot bless its unrelated policy edits."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    build = OrchestratorSessionBootstrap._build_workflow_tools

    def mutate(*, session: SloAgentSession, headless: bool) -> list:
        """Alter policy at the real construction seam, not the provenance checker."""
        config.reasoning_level = "high"
        return build(session=session, headless=headless)

    with patch.object(OrchestratorSessionBootstrap, "_build_workflow_tools", side_effect=mutate):
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._standard_orchestrator_attachment is None
    assert session._herdr_capture is None


@pytest.mark.parametrize("boundary", ["history", "activation", "model"])
async def test_preexisting_effective_mutation_is_not_an_intended_commit(
    tmp_path: Path, boundary: str
) -> None:
    """Only the value changed by the authorized gateway may be certified."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    session._active_reasoning_level = "high"
    if boundary == "history":
        session._history_session_ensured = False
        await session.rename_session(session_name="again")
    elif boundary == "activation":
        await session._prepare_herdr_capture_inputs(interactive=True)
    else:
        with patch.object(session, "_validate_model_selection_credential"):
            session.switch_model(model_name="gpt-5.5")
    assert session._herdr_capture is None


@pytest.mark.parametrize("field,value", [("model_name", "gpt-5.5"), ("reasoning_level", "high")])
async def test_first_activation_does_not_authorize_postbuild_edits(
    tmp_path: Path, field: str, value: str
) -> None:
    """Construction, not first reporting, establishes the original policy source."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low")
    session = SloAgentSession.build(config=config)
    config.__dict__[field] = value
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is None


async def test_removed_custom_prompt_cannot_acquire_standard_provenance(tmp_path: Path) -> None:
    """Matching the default later is not evidence of pristine construction."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", system_prompt="custom")
    session = SloAgentSession.build(config=config)
    config.system_prompt = None
    OrchestratorSessionBootstrap.attach(session=session)
    assert session._standard_orchestrator_attachment is None


async def test_malformed_pool_cannot_escape_ordinary_commit(tmp_path: Path) -> None:
    """Optional reporting validation cannot throw through a reasoning change."""
    config = SessionConfigDAO(workdir=tmp_path, model_pool_dao=configured_pool(), reasoning_level="low")
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    config.__dict__["model_pool_dao"] = object()
    session.switch_reasoning_level(reasoning_level="high")
    assert session._herdr_capture is None


@pytest.mark.parametrize("mutation", ["tools", "system", "append", "reasoning", "malformed"])
async def test_bootstrap_final_attachment_refuses_unexpected_additions(tmp_path: Path, mutation: str) -> None:
    """An edit inside attachment is not a standard addition merely because it succeeded."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    attach = session._attach_sub_agent_pool

    def mutate(*, pool: SubAgentPool, spawn_tools: list[BaseTool]) -> None:
        """Alter the real attached config before bootstrap's final verification."""
        attach(pool=pool, spawn_tools=spawn_tools)
        assert session._config is not None
        if mutation == "tools":
            session._config.extra_tools = list(reversed(spawn_tools))
        elif mutation == "system":
            session._config.system_prompt = "unexpected"
        elif mutation == "append":
            session._config.append_system_prompt = "unexpected"
        elif mutation == "malformed":
            session._config.__dict__["enable_history"] = 1
        else:
            session._config.reasoning_level = "high"

    with patch.object(session, "_attach_sub_agent_pool", side_effect=mutate):
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._standard_orchestrator_attachment is None
    assert session._herdr_capture is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra_tools", {}),
        ("extra_tools", ()),
        ("extra_tools", ""),
        ("plugin_paths", ()),
        ("plugin_paths", {}),
        ("model_name", False),
        ("reasoning_level", False),
        ("system_prompt", []),
        ("append_system_prompt", []),
    ],
)
async def test_malformed_source_contract_withdraws_capture(tmp_path: Path, field: str, value: object) -> None:
    """False-like containers must not masquerade as supported empty policy."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is not None
    assert session._config is not None
    session._config.__dict__[field] = value
    session._withdraw_stale_herdr_capture()
    assert session._herdr_capture is None


@pytest.mark.parametrize("field", ["priority", "cooldown_seconds", "rate_limit_cooldown_seconds"])
async def test_boolean_pool_scalar_cannot_equal_committed_integer(tmp_path: Path, field: str) -> None:
    """Python bool/int equality cannot retain a malformed pool's saved reference."""
    pool = configured_pool()
    pool.entries[0].__dict__[field] = 1
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_pool_dao=pool))
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is not None
    pool.entries[0].__dict__[field] = True
    session._withdraw_stale_herdr_capture()
    assert session._herdr_capture is None


@pytest.mark.parametrize(
    "container", ["tuple", "dict", "string", "none", "entry_dict", "entry_object", "entry_none"]
)
async def test_malformed_pool_sequence_withdraws_capture(tmp_path: Path, container: str) -> None:
    """Mutable pool objects must retain the actual list-of-entry contract."""
    pool = configured_pool()
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_pool_dao=pool))
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is not None
    values: dict[str, object] = {
        "tuple": tuple(pool.entries),
        "dict": {},
        "string": "",
        "none": None,
        "entry_dict": [entry.model_dump() for entry in pool.entries],
        "entry_object": [object(), pool.entries[1]],
        "entry_none": [None, pool.entries[1]],
    }
    pool.__dict__["entries"] = values[container]
    session._withdraw_stale_herdr_capture()
    assert session._herdr_capture is None


@pytest.mark.parametrize("boundary", ["construction", "bootstrap"])
async def test_optional_snapshot_failure_does_not_control_lifecycle(tmp_path: Path, boundary: str) -> None:
    """An ordinary snapshot fault refuses eligibility without escaping either caller."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
    if boundary == "construction":
        with patch.object(
            SloAgentSession, "_herdr_current_policy_sources", side_effect=RuntimeError("private")
        ):
            session = SloAgentSession.build(config=config)
    else:
        session = SloAgentSession.build(config=config)
        with patch.object(session, "_herdr_current_policy_sources", side_effect=RuntimeError("private")):
            OrchestratorSessionBootstrap.attach(session=session)
        assert session._sub_agent_pool is not None
    assert session._herdr_policy_invalidated
    assert session._herdr_capture is None
    assert session._standard_orchestrator_attachment is None


@pytest.mark.parametrize("boundary", ["before_attach", "after_attach"])
def test_optional_policy_comparison_failure_preserves_bootstrap(tmp_path: Path, boundary: str) -> None:
    """Later optional comparisons cannot escape after the initial snapshot succeeded."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    original = session._herdr_current_policy_sources
    calls = 0

    def snapshot() -> object:
        """Fail only the selected post-construction comparison boundary."""
        nonlocal calls
        calls += 1
        if calls == (2 if boundary == "before_attach" else 3):
            raise RuntimeError("private optional failure")
        return original()

    with patch.object(session, "_herdr_current_policy_sources", side_effect=snapshot):
        OrchestratorSessionBootstrap.attach(session=session)
    assert session._sub_agent_pool is not None
    assert session._standard_orchestrator_attachment is None
    assert session._herdr_capture is None
    assert session._herdr_policy_invalidated


@pytest.mark.parametrize("model_name", ["gpt-5.4", "moonshot-k2", "kimi-for-coding"])
async def test_valid_model_identity_retains_capture_without_mutation(tmp_path: Path, model_name: str) -> None:
    """Accepted model identities, including aliases, survive strict optional snapshots."""
    config = SessionConfigDAO(workdir=tmp_path, model_name=model_name)
    session = SloAgentSession.build(config=config)
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    capture = session._herdr_capture
    assert capture is not None
    generation = session._herdr_configuration_generation
    session._withdraw_stale_herdr_capture()
    assert session._herdr_capture == capture
    assert session._herdr_configuration_generation == generation
    assert not session._herdr_policy_invalidated


@pytest.mark.parametrize("custom_prompt", [None, "custom"])
async def test_construction_refuses_restore_not_ordinary_session(
    tmp_path: Path, custom_prompt: str | None
) -> None:
    """Optional strict revalidation must not add a disabled-mode construction failure."""
    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", system_prompt=custom_prompt)
    config.__dict__["enable_history"] = 1
    session = SloAgentSession.build(config=config)
    assert session.active_model_name == "gpt-5.4"
    assert not session._herdr_reporting_started
    assert session._herdr_policy_invalidated
    assert session._herdr_capture is None
    await session.rename_session(session_name="ordinary still works")
    assert session.session_name == "ordinary still works"


@pytest.mark.parametrize("malformed", [1, "true", None])
async def test_bootstrap_initial_snapshot_is_optional(tmp_path: Path, malformed: object) -> None:
    """Invalid reporting policy cannot prevent otherwise valid ordinary attachment."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

    config = SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4")
    session = SloAgentSession.build(config=config)
    config.__dict__["enable_history"] = malformed
    OrchestratorSessionBootstrap.attach(session=session)
    assert session._sub_agent_pool is not None
    assert session._standard_orchestrator_attachment is None
    assert session._herdr_capture is None


async def test_model_selection_before_activation_does_not_certify_edited_pool(tmp_path: Path) -> None:
    """No existing capture is required to detect mutation against construction."""
    config = SessionConfigDAO(workdir=tmp_path, model_pool_dao=configured_pool())
    session = SloAgentSession.build(config=config)
    assert config.model_pool_dao is not None
    config.model_pool_dao.entries[0].cooldown_seconds = 98
    with patch.object(session, "_validate_model_selection_credential"):
        session.switch_model(model_name="gpt-5.5")
    await session.rename_session(session_name="persisted")
    await session._prepare_herdr_capture_inputs(interactive=True)
    assert session._herdr_capture is None
