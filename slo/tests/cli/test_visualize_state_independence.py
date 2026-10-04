"""Real CLI visualize mounts history without touching hostile auth/catalog state."""

import json
import subprocess
import sys
from pathlib import Path

_HOSTILE_GLOBAL_FILES: dict[str, str] = {
    "model_catalog_cache.json": '{"schema_version": "2", "provider_slices": []}',
    "model_catalog_cache.v2.json": "{not json",
    "authentication.json": '{"schema_version":1,"providers":{"openrouter":{"provider":"openrouter","auth_type":"api_key","access_token":"synthetic-only"}}}',
    "authentication.additional-providers.json": "{not json",
}

_VISUALIZE_WITH_AUDIT: str = '''
import asyncio
import atexit
import json
import os
import sys
from pathlib import Path

_GLOBAL_DIR = Path(os.environ["SLO_HOME"]) / "global"
_EVENTS = {"open", "os.mkdir", "os.chmod", "os.rename", "os.replace", "os.remove", "os.unlink"}
_hits: list[list[str]] = []
_loaded: list[str] = []


def _audit(event: str, args: tuple[object, ...]) -> None:
    """Record both source and destination paths before any CLI import."""
    if event not in _EVENTS:
        return
    for arg in args:
        if isinstance(arg, (str, bytes, os.PathLike)):
            path = Path(os.path.realpath(os.fsdecode(arg)))
            if path.parent == _GLOBAL_DIR and path.name.startswith(("model_catalog", "authentication")):
                _hits.append([event, path.name])


sys.addaudithook(_audit)
atexit.register(lambda: print(json.dumps({"hits": _hits, "loaded": _loaded})))

from src.tui.headless_workflow_visualizer import HeadlessWorkflowVisualizer


async def _mount_headless(app: HeadlessWorkflowVisualizer) -> None:
    """Mount the actual app selected by CLI dispatch, then let Textual tear it down."""
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._workflow_data is not None
        _loaded.append(app._workflow_data.parent_session_id)


def _run_headless(self: HeadlessWorkflowVisualizer, **options: object) -> None:
    """Replace only the terminal driver, not parsing, dispatch, mount or loading."""
    asyncio.run(_mount_headless(self))


HeadlessWorkflowVisualizer.run = _run_headless
sys.argv = ["slo", "visualize", "--session", "observed", "--no-follow"]
from src.cli import main

main()
'''


def _seed_hostile_slo_home(*, root: Path) -> Path:
    """Seed synthetic hostile files and one complete history before the observer runs.

    Args:
        root (Path): This test's owned temporary directory.

    Returns:
        Path: Observer state root beneath root; every write is checked first.
    """
    slo_home = root / "observer-home"
    global_dir = slo_home / "global"
    session_dir = slo_home / "sessions/history/observed"
    for directory in (global_dir, session_dir):
        assert directory.resolve().is_relative_to(root.resolve())
        directory.mkdir(parents=True)
    files = {global_dir / name: text for name, text in _HOSTILE_GLOBAL_FILES.items()}
    files[session_dir / "session.json"] = json.dumps(
        {"session_id": "observed", "workdir": str(root), "model_name": "retired-model-x"}
    )
    events: list[tuple[str, dict[str, str]]] = [
        ("run_started", {}),
        ("user_message", {"role": "user", "content": "observer question"}),
        ("assistant_message", {"role": "assistant", "content": "observer answer"}),
        ("run_completed", {}),
    ]
    files[session_dir / "events.jsonl"] = "".join(
        json.dumps(
            {
                "session_id": "observed",
                "turn_id": "turn-1",
                "sequence": index,
                "kind": kind,
                "payload": payload,
            }
        )
        + "\n"
        for index, (kind, payload) in enumerate(iterable=events, start=1)
    )
    for path, text in files.items():
        assert path.resolve().is_relative_to(root.resolve())
        path.write_text(data=text, encoding="utf-8")
    return slo_home


def test_visualize_when_state_files_are_hostile_opens_no_catalog_or_credential_file(tmp_path: Path) -> None:
    """The actual command loads observed, records zero forbidden accesses and preserves bytes."""
    slo_home = _seed_hostile_slo_home(root=tmp_path)
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "SLO_HOME": str(slo_home),
        "SLO_AUTH_FILE": str(slo_home / "global/authentication.json"),
        "TMPDIR": str(tmp_path),
        "SLO_ENV": "test",
        "SLO_LOG_FORMAT": "text",
        "SLO_AUTO_VISUALIZE": "0",
        "SLO_PLUGINS_DISABLED": "1",
        "COLUMNS": "120",
        "LINES": "40",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        args=[sys.executable, "-B", "-c", _VISUALIZE_WITH_AUDIT],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report: dict[str, object] = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report == {"hits": [], "loaded": ["observed"]}
    for name, text in _HOSTILE_GLOBAL_FILES.items():
        assert (slo_home / "global" / name).read_text(encoding="utf-8") == text
