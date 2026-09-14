"""Canonical paths for orchestration durable files.

Sub-spec 71.a.0.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["OrchestrationLayout"]


class OrchestrationLayout:
    """Build the canonical paths below the session history root."""

    @classmethod
    def session_dir(cls, *, history_root: Path, session_id: str) -> Path:
        """Return the directory for one session.

        WHAT: Builds the root-relative session directory without touching disk.
        WHO: Called by orchestration stores and process wrappers.
        WHEN: Before an owner reads or writes session-scoped durable artifacts.

        Args:
            history_root (Path): Root containing session history directories.
            session_id (str): Session owning the requested directory.

        Returns:
            Path: Canonical directory for the session.
        """
        return history_root / session_id

    @classmethod
    def workflows_dir(cls, *, history_root: Path, owner_session_id: str) -> Path:
        """Return the workflow-handle directory for an owner session.

        WHAT: Builds the owner session's workflows directory path.
        WHO: Called by WorkflowHandleStore.
        WHEN: When the store lists, reads, or writes workflow handles.

        Args:
            history_root (Path): Root containing session history directories.
            owner_session_id (str): TUI session that owns the workflows.

        Returns:
            Path: Canonical directory containing workflow handle files.
        """
        return cls.session_dir(history_root=history_root, session_id=owner_session_id) / "workflows"

    @classmethod
    def workflow_handle_path(cls, *, history_root: Path, owner_session_id: str, workflow_id: str) -> Path:
        """Return the path for one workflow handle.

        WHAT: Builds the handle JSON path under the owner workflows directory.
        WHO: Called by WorkflowHandleStore.
        WHEN: When one handle is read or persisted.

        Args:
            history_root (Path): Root containing session history directories.
            owner_session_id (str): TUI session that owns the workflow.
            workflow_id (str): Identifier of the requested workflow.

        Returns:
            Path: Canonical JSON path for the workflow handle.
        """
        return (
            cls.workflows_dir(history_root=history_root, owner_session_id=owner_session_id)
            / f"{workflow_id}.json"
        )

    @classmethod
    def orchestrator_status_path(cls, *, history_root: Path, orchestrator_session_id: str) -> Path:
        """Return the self-reported status path for an orchestrator.

        WHAT: Builds the orchestrator status JSON path.
        WHO: Called by the headless status store in a later feature slice.
        WHEN: When the orchestrator reports lifecycle evidence.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Session ID of the orchestrator.

        Returns:
            Path: Canonical orchestrator status JSON path.
        """
        return (
            cls.session_dir(history_root=history_root, session_id=orchestrator_session_id)
            / "orchestrator.json"
        )

    @classmethod
    def fleet_path(cls, *, history_root: Path, orchestrator_session_id: str) -> Path:
        """Return the durable fleet snapshot path.

        WHAT: Builds the fleet JSON path for an orchestrator session.
        WHO: Called by FleetStore in a later feature slice.
        WHEN: When the pool persists a fleet projection.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Session ID of the orchestrator.

        Returns:
            Path: Canonical fleet snapshot JSON path.
        """
        return cls.session_dir(history_root=history_root, session_id=orchestrator_session_id) / "fleet.json"

    @classmethod
    def abort_request_path(cls, *, history_root: Path, orchestrator_session_id: str) -> Path:
        """Return the durable abort-request path.

        WHAT: Builds the abort request JSON path for an orchestrator session.
        WHO: Called by the workflow command service in a later feature slice.
        WHEN: When an operator requests a detached workflow abort.

        Args:
            history_root (Path): Root containing session history directories.
            orchestrator_session_id (str): Session ID of the orchestrator.

        Returns:
            Path: Canonical abort-request JSON path.
        """
        return (
            cls.session_dir(history_root=history_root, session_id=orchestrator_session_id)
            / "abort_request.json"
        )

    @classmethod
    def capture_path(cls, *, history_root: Path, session_id: str, name: str) -> Path:
        """Return a session-level capture file path.

        WHAT: Builds the named capture path below one session directory.
        WHO: Called by the shared capture-file opener.
        WHEN: Before opening an orchestrator stdout or stderr capture.

        Args:
            history_root (Path): Root containing session history directories.
            session_id (str): Session that owns the capture.
            name (str): Capture file name.

        Returns:
            Path: Canonical session-level capture file path.
        """
        return cls.session_dir(history_root=history_root, session_id=session_id) / name

    @classmethod
    def children_dir(cls, *, history_root: Path, parent_session_id: str) -> Path:
        """Return the directory containing an orchestrator's child captures.

        WHAT: Builds the parent session's ``children`` directory without touching disk.
        WHO: Called by child-capture writers and visualizer discovery readers.
        WHEN: Before scanning or addressing child-scoped orchestration artifacts.

        Args:
            history_root (Path): Root containing all session history directories.
            parent_session_id (str): Orchestrator session owning the children.

        Returns:
            Path: Canonical directory containing child capture directories.
        """
        return cls.session_dir(history_root=history_root, session_id=parent_session_id) / "children"

    @classmethod
    def child_capture_dir(cls, *, history_root: Path, parent_session_id: str, child_session_id: str) -> Path:
        """Return a child capture directory path.

        WHAT: Builds the parent/children/child directory without touching disk.
        WHO: Called by SubAgentProcess and child-status owners.
        WHEN: Before writing child captures or durable child state.

        Args:
            history_root (Path): Root containing all session history directories.
            parent_session_id (str): Orchestrator session owning the child.
            child_session_id (str): Child session whose capture directory is needed.

        Returns:
            Path: Canonical child capture directory below the history root.
        """
        return (
            cls.session_dir(history_root=history_root, session_id=parent_session_id)
            / "children"
            / child_session_id
        )

    @classmethod
    def child_status_path(cls, *, history_root: Path, parent_session_id: str, child_session_id: str) -> Path:
        """Return a child terminal-status path.

        WHAT: Builds the status JSON file below the child capture directory.
        WHO: Called by the child terminal-status owner in a later feature slice.
        WHEN: When a child reaches its durable terminal state.

        Args:
            history_root (Path): Root containing all session history directories.
            parent_session_id (str): Orchestrator session owning the child.
            child_session_id (str): Child session whose terminal status is needed.

        Returns:
            Path: Canonical child terminal-status JSON path.
        """
        return (
            cls.child_capture_dir(
                history_root=history_root,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
            )
            / "status.json"
        )
