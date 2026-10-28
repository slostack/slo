"""Build real archives in disposable source and import the extracted CSS resource."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


def test_archives_contain_exact_component_css_and_extracted_import(tmp_path: Path) -> None:
    """Poetry archives retain CSS, and isolated import resolves extracted source only."""
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("src", "config"):
        shutil.copytree(src=root / name, dst=source / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "install.sh"):
        shutil.copyfile(src=root / name, dst=source / name)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from poetry.core.masonry.api import build_wheel, build_sdist; "
            "build_wheel('dist'); build_sdist('dist')",
        ],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    resource = "src/tui/components/chat_transcript/css.tcss"
    expected = (root / resource).read_bytes()
    extraction = tmp_path / "wheel"
    with zipfile.ZipFile(next((source / "dist").glob("*.whl"))) as wheel:
        assert wheel.read(resource) == expected
        wheel.extractall(extraction)
    with tarfile.open(next((source / "dist").glob("*.tar.gz"))) as archive:
        member = next(item for item in archive.getmembers() if item.name.endswith("/" + resource))
        stream = archive.extractfile(member)
        assert stream is not None and stream.read() == expected
    program = (
        "import sys; from pathlib import Path; "
        f"root=Path({str(extraction)!r}); sys.path.insert(0,str(root)); "
        "import src.tui.components.chat_transcript.component as c; "
        "assert Path(c.__file__).is_relative_to(root); "
        "assert 'ChatTranscript .transcript-prepend-boundary' in c.ChatTranscript.DEFAULT_CSS"
    )
    subprocess.run(
        [sys.executable, "-I", "-c", program],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "SLO_ENV": "test"},
    )


def test_adapter_import_orders_are_acyclic(tmp_path: Path) -> None:
    """Fresh interpreters import local adapters before and after their runtime owners."""
    root = Path(__file__).resolve().parents[2]
    modules = [
        "src.tui.components.chat_transcript.adapters.transcript",
        "src.tui.components.chat_transcript.adapters.workflow_notice",
        "src.tui.components.chat_transcript.adapters.workflow_progress",
        "src.tui.components.chat_transcript.component",
        "src.tui.app",
    ]
    for order in (modules, list(reversed(modules))):
        program = (
            f"import sys,importlib; sys.path.insert(0,{str(root)!r}); "
            f"[importlib.import_module(name) for name in {order!r}]"
        )
        subprocess.run(
            [sys.executable, "-I", "-c", program], cwd=tmp_path, check=True, capture_output=True, text=True
        )
