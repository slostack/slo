"""Every third-party import in the shipped code must be a declared dependency.

A ``pipx install`` builds the wheel and installs exactly what
``[project] dependencies`` names — ``poetry.lock`` is not consulted, and
neither are the dev groups. Anything imported but not declared therefore
survives only as long as some *other* dependency keeps pulling it in.

That contract broke in v0.16.x. ``src/cli/app.py`` imported ``click``
directly, relying on Typer to supply it. Typer 0.20 vendored Click as
``typer._click`` and dropped the ``click`` dependency, so a clean install
had no ``click`` and every ``slo`` invocation died with
``ModuleNotFoundError: No module named 'click'``. Dev machines never saw
it: the dev-group ``black`` installs ``click``.

This test parses the shipped packages, resolves each third-party import
to its distribution name, and asserts that name is declared. It is a
plain AST walk — no build, no network — so it runs in the default suite
rather than behind the ``e2e`` marker that kept the installer smoke test
from catching this.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# Packages that ship inside the wheel and therefore run on end-user machines.
_SHIPPED_PACKAGE_DIRS: tuple[str, ...] = ("src", "config")

# Import name → distribution name, for the cases where they differ. Every
# other import maps by lowercasing and swapping ``_`` for ``-``.
_IMPORT_TO_DISTRIBUTION: dict[str, str] = {
    "PIL": "pillow",
    "yaml": "pyyaml",
    "pythonjsonlogger": "python-json-logger",
    "markdown_it": "markdown-it-py",
}

# Imports deliberately left undeclared because they are optional: the code
# guards them behind a flag and degrades cleanly when absent.
_OPTIONAL_IMPORTS: frozenset[str] = frozenset({"debugpy"})

# First-party import roots — resolved from the checkout, never installed.
_FIRST_PARTY_ROOTS: frozenset[str] = frozenset({"src", "config", "tests"})


def _declared_distributions() -> set[str]:
    """Read the normalized distribution names from ``[project] dependencies``.

    Returns:
        set[str]: Declared runtime distributions, lowercased with ``_``
            and ``.`` normalized to ``-`` per PEP 503.
    """
    pyproject: dict = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements: list[str] = pyproject["project"]["dependencies"]
    return {_normalize(_requirement_name(requirement)) for requirement in requirements}


def _requirement_name(requirement: str) -> str:
    """Extract the distribution name from a PEP 508 requirement string.

    Args:
        requirement (str): A requirement such as ``"httpx (>=0.28.1,<0.29.0)"``.

    Returns:
        str: The bare distribution name, e.g. ``"httpx"``.
    """
    return re.split(r"[\s\[(<>=!;~]", requirement.strip(), maxsplit=1)[0]


def _normalize(name: str) -> str:
    """Normalize a distribution name to its PEP 503 comparison form.

    Args:
        name (str): A distribution name in any casing or separator style.

    Returns:
        str: The lowercased name with runs of ``-``, ``_``, ``.`` collapsed to ``-``.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _imported_roots(*, package_dir: Path) -> dict[str, Path]:
    """Collect every top-level import name used under ``package_dir``.

    Args:
        package_dir (Path): Directory of shipped Python source to scan.

    Returns:
        dict[str, Path]: Import root name mapped to one file that imports it,
            so a failure can name the offending module.
    """
    roots: dict[str, Path] = {}
    for source_file in sorted(package_dir.rglob("*.py")):
        tree: ast.Module = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for root in _import_roots_of_node(node=node):
                roots.setdefault(root, source_file)
    return roots


def _import_roots_of_node(*, node: ast.AST) -> list[str]:
    """Return the top-level import names an AST node introduces.

    Relative imports are skipped: they are always first-party.

    Args:
        node (ast.AST): Any node from a parsed module.

    Returns:
        list[str]: Top-level import names, empty for non-import nodes.
    """
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module.split(".")[0]]
    return []


def _is_third_party(*, root: str) -> bool:
    """Return whether an import root resolves to an installed distribution.

    Args:
        root (str): A top-level import name.

    Returns:
        bool: False for the standard library, first-party packages, and
            imports explicitly marked optional.
    """
    if root in sys.stdlib_module_names:
        return False
    if root in _FIRST_PARTY_ROOTS:
        return False
    return root not in _OPTIONAL_IMPORTS


class TestDeclaredDependencies:
    """Hold ``[project] dependencies`` to what the shipped code imports."""

    def test_every_third_party_import_is_declared(self) -> None:
        """No shipped module may import a distribution the wheel does not require."""
        declared: set[str] = _declared_distributions()

        undeclared: dict[str, Path] = {}
        for package_name in _SHIPPED_PACKAGE_DIRS:
            imported: dict[str, Path] = _imported_roots(package_dir=_REPO_ROOT / package_name)
            for root, source_file in imported.items():
                if not _is_third_party(root=root):
                    continue
                distribution: str = _normalize(_IMPORT_TO_DISTRIBUTION.get(root, root))
                if distribution not in declared:
                    undeclared[root] = source_file

        assert not undeclared, (
            "these imports are not declared in [project] dependencies, so a "
            "pipx install only works while another package happens to supply "
            "them:\n"
            + "\n".join(
                f"  {root} — imported by {path.relative_to(_REPO_ROOT)}"
                for root, path in sorted(undeclared.items())
            )
        )

    def test_click_is_not_imported_by_shipped_code(self) -> None:
        """``click`` must reach the code only as Typer's vendored ``typer._click``.

        Declaring ``click`` would install a *different* Click than the one
        Typer 0.20+ actually uses, so the fix is to not import it at all.
        """
        importers: list[Path] = [
            source_file
            for package_name in _SHIPPED_PACKAGE_DIRS
            for root, source_file in _imported_roots(package_dir=_REPO_ROOT / package_name).items()
            if root == "click"
        ]

        assert not importers, (
            "shipped code imports `click` directly; use `typer.Context` and "
            "`typer.core` instead — Typer vendors Click and no longer depends "
            f"on the distribution. Offending files: {importers}"
        )
