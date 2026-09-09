"""Consumer-only contract tests for the bundled Bash live-output plugin."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from src.agents.slo_agent.plugins.api import PluginAPI
from src.agents.slo_agent.plugins.dao import PluginHealthDAO, PluginRegistrationDAO

_PLUGIN_PATH: Path = Path(__file__).parents[2] / "plugins" / "bash_live_output" / "plugin.py"


def _load_plugin_module() -> ModuleType:
    """Load the bundled source without installing or executing a subprocess.

    Returns:
        ModuleType: The bundled plugin module for contract inspection.
    """
    spec = importlib.util.spec_from_file_location("bundled_bash_live_output", _PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_registration() -> PluginRegistrationDAO:
    """Build one API recording target for the bundled plugin.

    Returns:
        PluginRegistrationDAO: Empty registration record populated by the plugin.
    """
    return PluginRegistrationDAO(
        plugin_id="slo-slo",
        source_path=str(_PLUGIN_PATH),
        health=PluginHealthDAO(plugin_id="slo-slo", source_path=str(_PLUGIN_PATH)),
    )


def test_bundled_plugin_registers_only_observer_and_bash_renderer() -> None:
    """The bundled plugin is a core-stream consumer and registers no tool or command."""
    module: ModuleType = _load_plugin_module()
    registration: PluginRegistrationDAO = _build_registration()

    module.register(PluginAPI(registration=registration))

    assert list(registration.event_handlers) == ["tool_output_update"]
    assert list(registration.renderers) == ["bash"]
    assert registration.tools == []
    assert registration.commands == {}
    assert registration.before_tool_call_handlers == []
    assert registration.after_tool_result_handlers == []
    assert registration.before_agent_turn_handlers == []


def test_bundled_renderer_preserves_unrecognized_raw_output() -> None:
    """Any Bash output remains visible when no optional format is recognized."""
    module: ModuleType = _load_plugin_module()
    raw_output: str = "custom-build: phase 7\nnot a known test format"

    assert module._render_bash_output(raw_output) == raw_output


def test_bundled_manifest_declares_only_plugin_payload() -> None:
    """The bundled plugin ships as a managed-installer-compatible payload."""
    manifest_path: Path = _PLUGIN_PATH.parent / "slo-plugin.json"

    assert manifest_path.exists()
    assert '"entry_point": "plugin.py"' in manifest_path.read_text(encoding="utf-8")
