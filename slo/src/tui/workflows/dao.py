"""Domain objects for the detached-workflow TUI receive path (spec 57.a.5).

Pure data and parsing/validation helpers: no Textual imports, no
filesystem access, no visualizer side effects. The app service in
``service.py`` consumes these objects; the renderer in ``renderer.py``
consumes the effect objects.
"""

from __future__ import annotations

import json
from typing import List, Literal, Optional, TypeAlias, cast, get_args

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowState

__all__ = [
    "DetachedWorkflowUiEffect",
    "DetachedWorkflowUiEffectDAO",
    "HandleAdvanceOutcomeDAO",
    "LiveWorkflowLabelDAO",
    "LaunchResultOutcome",
    "ParsedLaunchResultDAO",
    "ParsedWorkflowLifecycleMessageDAO",
    "WorkflowLifecycleTarget",
    "workflow_lifecycle_target_for_kind",
    "parse_workflow_lifecycle_message",
    "parse_launch_workflow_result",
]

WorkflowLifecycleTarget: TypeAlias = Literal["started", "terminal"]
"""Claimed workflow lifecycle note kind mapped to its durable-side effect.

``workflow_started`` advances the handle to ``running`` and fires the
resume-case visualizer fallback; ``workflow_completed`` / ``workflow_failed``
advance to their terminal states and free the visualizer launch guard.
"""

_WORKFLOW_KIND_TO_STATE: dict[str, WorkflowState] = {
    "workflow_started": "running",
    "workflow_completed": "completed",
    "workflow_failed": "failed",
}
"""Claimed workflow lifecycle note kind → durable handle state (spec 57.a.5)."""

_WORKFLOW_KIND_TO_TARGET: dict[str, WorkflowLifecycleTarget] = {
    "workflow_started": "started",
    "workflow_completed": "terminal",
    "workflow_failed": "terminal",
}
"""Claimed workflow lifecycle note kind → lifecycle side-effect target."""

LaunchResultOutcome: TypeAlias = Literal["launched", "ignored"]
"""Outcome of translating one ``launch_workflow`` tool-result text."""

DetachedWorkflowUiEffect: TypeAlias = Literal["launch_visualizer", "reset_launch_guard"]
"""A typed UI effect the renderer knows how to execute.

``launch_visualizer`` opens the visualizer window (guarded, once per
orchestrator session id); ``reset_launch_guard`` frees that guard so a
re-run of the workflow opens a fresh window. The reset effect is emitted
only by the terminal lifecycle path — it never launches anything.
"""


class ParsedWorkflowLifecycleMessageDAO(BaseModel):
    """Validated, typed view of one claimed workflow lifecycle inbox message.

    Built only for inbox kinds in ``_WORKFLOW_KIND_TO_TARGET`` with a
    path-safe non-empty ``workflow_id``; every other inbox message parses to
    ``None`` and is a no-op for the workflow receive path.
    """

    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(description="Workflow identifier from the inbox payload.")
    orchestrator_session_id: str = Field(
        default="",
        description="Detached orchestrator session id, or ``" "`` when absent.",
    )
    target_state: WorkflowState = Field(
        description="Durable handle state the lifecycle note maps to.",
    )
    target: WorkflowLifecycleTarget = Field(
        description="Lifecycle side-effect target: ``started`` or ``terminal``.",
    )


class ParsedLaunchResultDAO(BaseModel):
    """Validated, typed view of one ``launch_workflow`` tool-result payload."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(
        default="",
        description="Workflow identifier, or ``" "`` when the result omits it.",
    )
    orchestrator_session_id: str = Field(
        description="Detached orchestrator session id to visualise.",
    )
    state: WorkflowState = Field(
        default="launching",
        description="State to seed in the live-state cache; defaults to ``launching``.",
    )


class LiveWorkflowLabelDAO(BaseModel):
    """One live (``launching``/``running``) workflow label for exit hints."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(description="Workflow identifier.")
    state: WorkflowState = Field(description="Current cached workflow state.")


class DetachedWorkflowUiEffectDAO(BaseModel):
    """One typed UI effect emitted by the app service for the renderer.

    ``state`` carries the typed durable lifecycle state that motivated the
    effect — the renderer (not the app) decides how to interpret it, so a
    terminal ``reset_launch_guard`` effect flows end-to-end without the app
    ever branching on raw payload fields.
    """

    model_config = ConfigDict(frozen=True)

    effect: DetachedWorkflowUiEffect = Field(description="Effect kind to execute.")
    orchestrator_session_id: str = Field(
        description="Detached orchestrator session id the effect targets.",
    )
    state: WorkflowState = Field(
        default="launching",
        description="Typed durable lifecycle state the effect carries.",
    )


class HandleAdvanceOutcomeDAO(BaseModel):
    """Result of translating one claimed inbox message into durable/UI effects.

    ``effects`` is non-empty only for the started/terminal paths the
    renderer acts on; the durable handle advance and the state-cache update
    are expressed through ``advanced_handle`` / ``advanced_state`` so the
    app (and tests) can assert exactly which side of the translation fired.
    """

    model_config = ConfigDict(frozen=True)

    effects: List[DetachedWorkflowUiEffectDAO] = Field(
        default_factory=list,
        description="Typed UI effects for the renderer to execute.",
    )
    advanced_handle: bool = Field(
        default=False,
        description="True when the durable handle was successfully advanced.",
    )
    advanced_state: Optional[WorkflowState] = Field(
        default=None,
        description="Newly cached workflow state when the advance succeeded.",
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description="Workflow identifier the outcome concerns, when known.",
    )


_UNSAFE_WORKFLOW_ID_MARKERS: tuple[str, ...] = ("/", "\\", "..", "\x00")
"""Path-meta sequences rejected in workflow ids (mirrors the handle store).

Inbox payloads are untrusted cross-process data; an id that could escape
the per-session ``workflows/`` directory is treated as "no lifecycle
payload" and no-ops exactly like a non-workflow message.
"""


def workflow_lifecycle_target_for_kind(*, kind: str) -> Optional[WorkflowLifecycleTarget]:
    """Return the lifecycle side-effect target for an inbox message kind.

    Args:
        kind (str): Inbox message kind (``workflow_started`` etc.).

    Returns:
        Optional[WorkflowLifecycleTarget]: ``started``/``terminal`` for
            workflow lifecycle kinds, ``None`` for every other kind.
    """
    return _WORKFLOW_KIND_TO_TARGET.get(kind)


def parse_workflow_lifecycle_message(
    *,
    kind: str,
    payload: Optional[dict[str, object]],
) -> Optional[ParsedWorkflowLifecycleMessageDAO]:
    """Parse and validate one claimed inbox message into a lifecycle payload.

    WHAT: the single validation seam for inbox-originated workflow lifecycle
        data. Non-workflow kinds, empty/unsafe workflow ids, and unknown
        kinds all parse to ``None`` — the caller treats them as no-ops.
    WHO: ``DetachedWorkflowAppService.advance_from_inbox_message``.
    WHEN: on every claimed inbox message, before any durable or UI effect.

    Args:
        kind (str): Inbox message kind.
        payload (Optional[dict[str, object]]): Raw opaque inbox payload.

    Returns:
        Optional[ParsedWorkflowLifecycleMessageDAO]: Typed lifecycle payload,
            or ``None`` when the message is not an actionable workflow
            lifecycle note.
    """
    target_state: Optional[WorkflowState] = _WORKFLOW_KIND_TO_STATE.get(kind)
    if target_state is None:
        return None
    raw_payload: dict[str, object] = payload or {}
    workflow_id: str = str(raw_payload.get("workflow_id", ""))
    if not _is_path_safe_workflow_id(workflow_id=workflow_id):
        return None
    return ParsedWorkflowLifecycleMessageDAO(
        workflow_id=workflow_id,
        orchestrator_session_id=str(raw_payload.get("orchestrator_session_id", "")),
        target_state=target_state,
        target=_WORKFLOW_KIND_TO_TARGET[kind],
    )


def parse_launch_workflow_result(*, result_text: str) -> Optional[ParsedLaunchResultDAO]:
    """Parse and validate one ``launch_workflow`` tool-result text.

    WHAT: the single parsing seam for the launch turn's tool-result JSON.
        Malformed JSON, non-dict payloads, error JSON, and payloads without
        an orchestrator session id all parse to ``None`` — safe, no launch.
    WHO: ``DetachedWorkflowAppService.advance_from_launch_result``.
    WHEN: when a ``launch_workflow`` ``tool_result`` event streams through
        the live render path.

    Args:
        result_text (str): Raw ``launch_workflow`` tool-result text.

    Returns:
        Optional[ParsedLaunchResultDAO]: Typed launch result, or ``None``
            when the result carries no actionable orchestrator session id.
    """
    parsed: Optional[dict[str, object]] = _loads_dict_or_none(result_text=result_text)
    if parsed is None:
        return None
    orchestrator_session_id: str = str(parsed.get("orchestrator_session_id") or "")
    if not orchestrator_session_id:
        return None
    workflow_id: str = str(parsed.get("workflow_id") or "")
    state: WorkflowState = _coerce_workflow_state(value=parsed.get("state"))
    return ParsedLaunchResultDAO(
        workflow_id=workflow_id,
        orchestrator_session_id=orchestrator_session_id,
        state=state,
    )


def _loads_dict_or_none(*, result_text: str) -> Optional[dict[str, object]]:
    """Decode ``result_text`` into a JSON object or return ``None``.

    Args:
        result_text (str): Raw tool-result text.

    Returns:
        Optional[dict[str, object]]: Decoded JSON object, or ``None`` for
            malformed JSON or a non-object payload.
    """
    try:
        decoded: object = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(decoded, dict):
        return None
    return cast(dict[str, object], decoded)


def _coerce_workflow_state(*, value: object) -> WorkflowState:
    """Coerce an untrusted JSON ``state`` field to a valid ``WorkflowState``.

    Args:
        value (object): Raw JSON value for the handle ``state`` field.

    Returns:
        WorkflowState: The value when it is a valid workflow state, else
            ``launching``.
    """
    candidate: str = str(value or "launching")
    if candidate in get_args(WorkflowState):
        return cast(WorkflowState, candidate)
    return "launching"


def _is_path_safe_workflow_id(*, workflow_id: str) -> bool:
    """Return whether a workflow id is safe to use as a file name.

    Args:
        workflow_id (str): Candidate workflow id from an inbox payload.

    Returns:
        bool: ``True`` when the id is non-empty and free of path metas.
    """
    if not workflow_id:
        return False
    return not any(marker in workflow_id for marker in _UNSAFE_WORKFLOW_ID_MARKERS)
