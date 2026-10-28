"""Read-only signature and field-description audit for the finite R158-2 scope.

Repository/product path normalization: this script runs from the product
subdirectory (``slo/``), while plain ``git diff --name-only`` emits
repository-root-relative paths (``slo/tests/...``). All Git enumeration uses
``git diff --relative`` / ``git ls-files`` so every candidate is already
product-relative. A candidate that is not a real file is an audit failure,
never a silent skip.
"""

import ast
import subprocess
from pathlib import Path

ROOT = Path("docs/implementation/94-herdr/conventions-revision-159-receipts")
BASE = "d0e3a756689f2675e5507034d43cd8b272d3c6b8"
# Subdirectory prefix prepended when addressing repository-root blobs; empty at
# the repository root. Derived from the product checkout layout, not cwd.
PRODUCT_PREFIX = "slo/"


def signatures(text: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index nested definitions by their lexical ownership, not line numbers."""
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        """Preserve class/function ownership while traversing statement containers."""
        for child in ast.iter_child_nodes(node):
            scope = prefix
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = prefix + "." + child.name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[scope] = child
            visit(node=child, prefix=scope)

    visit(node=ast.parse(text), prefix="")
    return found


def incomplete(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Include positional-only and variadic parameters in explicit-type checks."""
    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
    return node.returns is None or any(
        arg.annotation is None for arg in args if arg.arg not in ("self", "cls")
    )


def main() -> None:
    """Check owned, untracked-new, and tracked-changed definitions; fail on gaps."""
    owned = ROOT.joinpath("files.txt").read_text().splitlines()
    new = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "src", "tests"], text=True
    ).splitlines()
    # --relative keeps paths product-relative from this nested cwd; plain
    # --name-only would emit repository-root paths that do not exist here.
    changed = subprocess.check_output(
        ["git", "diff", "--relative", "--name-only", BASE, "--", "src", "tests"], text=True
    ).splitlines()
    failures: list[str] = []
    count = 0
    for filename in sorted(set(owned + new + changed)):
        path = Path(filename)
        if path.suffix != ".py":
            continue
        if not path.is_file():
            failures.append(f"{filename}: MISSING candidate path from Git enumeration")
            continue
        current = signatures(path.read_text())
        previous = {}
        if filename not in new and filename not in owned:
            result = subprocess.run(
                ["git", "show", BASE + ":" + PRODUCT_PREFIX + filename],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                previous = signatures(result.stdout)
        for name, node in current.items():
            if name in previous:
                continue
            count += 1
            if incomplete(node):
                failures.append(f"{filename}:{node.lineno} {name}")
    for node in ast.walk(ast.parse(Path(owned[0]).read_text())):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in ("queue", "chunk_queue", "bound_tools"):
                assert isinstance(node.value, ast.Call)
                assert any(keyword.arg == "description" for keyword in node.value.keywords)
    print(f"Checked {count} owned/new definitions including nested helpers and variadic arguments.")
    print(
        "\n".join(failures)
        if failures
        else "PASS: no incomplete signatures; all three Faux fields described."
    )
    assert not failures


if __name__ == "__main__":
    main()
