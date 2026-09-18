"""Characterize slash parsing, plugin precedence, and closed router effects."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.slash_router import SlashCommandResultDAO, SlashRouter
from tests.characterization.baseline_contract import BaselineComparator
from tests.characterization.capture import baseline_case, canonical_json_bytes, loaded_baseline_ledger
from tests.characterization.normalizers import normalize_baseline_capture

_FIXTURE_PATH: Path = Path("tests/fixtures/79_tui_v2/baseline/slash/parser_and_effects.json")
_CASE_ID: str = "slash-parser-plugin-precedence-effects"


async def test_parser_plugin_precedence_and_effects_match_baseline() -> None:
    """Freeze parser remainder, plugin precedence, and built-in result effects.

    WHAT: Drives the real slash router with a session-local plugin registry seam
        and a normal built-in command, preserving selected-handler behavior.
    WHO: Later slash bridge work uses this fixture as the compatibility oracle.
    WHEN: Before an integration migration changes parser or router mechanics.
    """
    session: MagicMock = _session_stub()
    plugin_calls: list[dict[str, str]] = []

    async def plugin_handler(*, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Capture plugin dispatch while returning a closed result object.

        WHAT: Represents one registered plugin handler without loading a plugin.
        WHO: SlashRouter dispatches it after resolving the built-in command token.
        WHEN: Only in the precedence characterization case.

        Args:
            rest (str): Parser-preserved trailing command text.
            session (SloAgentSession): Active session supplied by the router.

        Returns:
            SlashCommandResultDAO: Plugin-owned rendering outcome.
        """
        del session
        plugin_calls.append({"handler": "plugin", "rest": rest})
        return SlashCommandResultDAO(rendered=f"plugin:{rest}", should_clear=True)

    session._plugin_registry = object()
    session.plugin_command_handler.return_value = plugin_handler
    plugin_token, plugin_remainder = SlashRouter._parse_line(line="/clear plugin remainder")
    plugin_result: SlashCommandResultDAO = await SlashRouter.dispatch(
        line="/clear plugin remainder",
        session=session,
    )
    session._plugin_registry = None
    builtin_token, builtin_remainder = SlashRouter._parse_line(line="/clear")
    builtin_result: SlashCommandResultDAO = await SlashRouter.dispatch(line="/clear", session=session)
    capture: dict[str, object] = {
        "builtin": {
            "remainder": builtin_remainder,
            "result": builtin_result.model_dump(),
            "token": builtin_token,
        },
        "plugin": {
            "calls": plugin_calls,
            "remainder": plugin_remainder,
            "result": plugin_result.model_dump(),
            "token": plugin_token,
        },
    }
    observed: bytes = normalize_baseline_capture(
        capture=canonical_json_bytes(value=capture),
        case_id=_CASE_ID,
    )
    BaselineComparator.compare(
        case=baseline_case(case_id=_CASE_ID, artifact_relative_path="slash/parser_and_effects.json"),
        observed=observed,
        expected=_FIXTURE_PATH.read_bytes(),
        ledger=loaded_baseline_ledger(),
    )


def _session_stub() -> MagicMock:
    """Build the narrow router-facing session fake.

    WHAT: Supplies the actual attributes used by parser precedence and clear.
    WHO: The slash characterization passes it to the production router.
    WHEN: Once for the b.2 slash capture.

    Returns:
        MagicMock: SloAgentSession-specified slash session fake.
    """
    session: MagicMock = MagicMock(spec=SloAgentSession)
    session._plugin_registry = None
    session.plugin_command_handler = MagicMock()
    return session
