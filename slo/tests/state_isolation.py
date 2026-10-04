"""Test-only state boundaries; import this before any config or application module."""

import os
import tempfile
from pathlib import Path

SLO_HOME_BINDINGS: tuple[tuple[str, str], ...] = (
    ("src.agents.model_catalog.store", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.history.filesystem_store", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.history.migration.token_usage_backfiller", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.history.migration.tree_migrator", "_CFG_SLO_HOME"),
    ("src.agents.slo_agent.orchestrator.pool", "SLO_HOME"),
    ("src.agents.slo_agent.preferences.service", "_CFG_SLO_HOME"),
    ("src.auth.credential_refresher", "_CFG_SLO_HOME"),
    ("src.cli.typer_dispatch", "_CFG_SLO_HOME"),
    ("src.integrations.connectors.store", "_CFG_SLO_HOME"),
    ("src.scheduling.os.logs", "_CFG_SLO_HOME"),
    ("src.scheduling.store", "_CFG_SLO_HOME"),
)
"""Module-level SLO_HOME imports; an AST regression guard keeps this exhaustive."""

INHERITED_STATE_OVERRIDES: tuple[str, ...] = (
    "SLO_WORKFLOW_ID",
    "SLO_CAPTURE_DIR",
    "SLO_CAPTURE_COMPLETION",
    "SLO_PREFERENCES_FILE",
    "SLO_SCHEDULES_DIR",
    "SLO_CONNECTORS_DIR",
    "SLO_MODEL_CATALOG_OVERRIDES_FILE",
    "SLO_USER_SKILLS_DIR",
    "SLO_USER_WORKFLOWS_DIR",
    "SLO_KB_DIR",
    "KB_DIR",
    "SLO_SKILLS_DIR",
    "SLO_KB_SOURCE",
    "SLO_TOOL_BASE_DIR",
    "SLO_SESSION_ID",
)
"""State and content overrides that must not escape the test-owned home."""


def isolate_suite_slo_home() -> Path:
    """Redirect default state before conftest imports application modules.

    WHO: The root conftest calls this once before collection. Its unconfigure
    hook removes the returned directory after pytest finishes.

    Returns:
        Path: A fresh, resolved suite root under the command's temporary root.
    """
    root: Path = Path(tempfile.mkdtemp(prefix="slo-test-home-")).resolve()
    os.environ["SLO_HOME"] = str(root)
    os.environ["SLO_AUTH_FILE"] = str(root / "global" / "authentication.json")
    os.environ["HOME"] = str(root / "home")
    for name in INHERITED_STATE_OVERRIDES:
        os.environ.pop(name, None)
    return root
