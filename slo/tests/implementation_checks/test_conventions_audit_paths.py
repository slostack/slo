"""Regression for the finite signature audit's nested-product Git enumeration (R173-2).

The audit at ``docs/implementation/94-herdr/conventions-revision-159-receipts/audit.py``
runs from the product subdirectory. Its tracked-changed enumeration must use
``git diff --relative --name-only`` so repository-root-relative ``slo/...``
paths cannot silently skip real tracked files, and a missing candidate path
must fail the audit instead of being skipped. These tests copy the real audit
into a synthetic nested Git repository; they never mutate the host repository
and write only inside the pytest temp root.

Discovery sensitivity: the tracked-discovery subject below lives in
``src/tracked_after.py`` — a separate file created and committed only after
the base commit, absent from the explicit owned inventory (``files.txt``) and
absent from the untracked set — so only the ``git diff --relative``
enumeration can reach it.
``test_discovery_tests_reject_removed_tracked_enumeration`` reruns the same
untyped subject against a mutant audit whose tracked enumeration is removed
and requires the mutant to clear it, proving these discovery tests genuinely
reject omitted discovery (and therefore the root-relative path regression
that silently empties the enumeration).
"""

import os
import subprocess
from pathlib import Path

AUDIT = (
    Path(__file__).resolve().parents[2]
    / "docs/implementation/94-herdr/conventions-revision-159-receipts/audit.py"
)

_TRACKED_ENUMERATION = """changed = subprocess.check_output(
        ["git", "diff", "--relative", "--name-only", BASE, "--", "src", "tests"], text=True
    ).splitlines()"""


def _git(*, root: Path, arguments: list[str]) -> str:
    """Run one Git command inside the synthetic repository root."""
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True)


def _commit_all(*, root: Path, message: str) -> None:
    """Commit every staged and unstaged change inside the synthetic repository."""
    _git(root=root, arguments=["add", "-A"])
    _git(
        root=root,
        arguments=[
            "-c",
            "user.name=audit-regression",
            "-c",
            "user.email=audit-regression@example.invalid",
            "commit",
            "-q",
            "-m",
            message,
        ],
    )


def _init_nested_repo(*, tmp_path: Path) -> Path:
    """Create a synthetic repo/product/product-receipts layout with a base commit."""
    root = tmp_path / "repo"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    product = root / "slo"
    receipts = product / "docs/receipts"
    src = product / "src"
    receipts.mkdir(parents=True)
    src.mkdir(parents=True)
    src.joinpath("tracked.py").write_text(
        "def base_function(flag: bool) -> bool:\n"
        '    """Pre-existing annotated definition."""\n'
        "    return flag\n"
    )
    (product / "docs/receipts/files.txt").write_text("src/tracked.py\n")
    _git(root=root, arguments=["init", "-q"])
    _git(root=root, arguments=["checkout", "-q", "-b", "main"])
    _commit_all(root=root, message="base")
    return product


def _install_audit(*, product: Path, base: str, source: Path) -> Path:
    """Place the audit script with the synthetic base commit patched in."""
    target = product / "docs/receipts/audit.py"
    text = source.read_text()
    text = text.replace('BASE = "d0e3a756689f2675e5507034d43cd8b272d3c6b8"', f'BASE = "{base}"')
    text = text.replace(
        'ROOT = Path("docs/implementation/94-herdr/conventions-revision-159-receipts")',
        'ROOT = Path("docs/receipts")',
    )
    target.write_text(text)
    return target


def _run_audit(*, product: Path, script: Path) -> subprocess.CompletedProcess[str]:
    """Run the audit from the nested product cwd without touching the real repo."""
    return subprocess.run(
        ["python", str(script)],
        cwd=product,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )


def _prepare_discovery_case(
    *, tmp_path: Path, annotated: bool, source: Path
) -> subprocess.CompletedProcess[str]:
    """Run the audit against one new Git-only-discovered tracked definition.

    The subject lives in ``src/tracked_after.py``, committed after the base
    commit, absent from ``files.txt`` and absent from the untracked set, so the
    audit can reach it only through ``git diff --relative``.
    """
    product = _init_nested_repo(tmp_path=tmp_path)
    base = _git(root=product.parent, arguments=["rev-parse", "HEAD"]).strip()
    if annotated:
        body = (
            "def new_tracked_definition(value: int) -> int:\n"
            '    """New tracked definition with complete annotations."""\n'
            "    return value\n"
        )
    else:
        body = (
            "def new_tracked_definition(untyped):\n"
            '    """New tracked definition missing one annotation."""\n'
            "    return untyped\n"
        )
    (product / "src/tracked_after.py").write_text(body)
    _commit_all(root=product.parent, message="tracked addition")
    script = _install_audit(product=product, base=base, source=source)
    return _run_audit(product=product, script=script)


def test_audit_flags_new_tracked_definition_from_nested_product_cwd(tmp_path: Path) -> None:
    """A newly added tracked definition is discovered and checked from ``slo/``.

    The subject file is absent from ``files.txt`` and from the untracked set,
    so this fails only when the ``git diff --relative`` enumeration works.
    """
    result = _prepare_discovery_case(tmp_path=tmp_path, annotated=False, source=AUDIT)
    assert result.returncode != 0
    assert "src/tracked_after.py" in result.stdout
    assert "new_tracked_definition" in result.stdout


def test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd(tmp_path: Path) -> None:
    """A fully annotated newly added tracked definition leaves the audit green.

    The subject file is absent from ``files.txt`` and from the untracked set,
    so this proves the tracked enumeration finds it and accepts its types.
    """
    result = _prepare_discovery_case(tmp_path=tmp_path, annotated=True, source=AUDIT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MISSING" not in result.stdout


def test_audit_fails_on_missing_candidate_path(tmp_path: Path) -> None:
    """An owned candidate that vanished from disk fails instead of being skipped."""
    product = _init_nested_repo(tmp_path=tmp_path)
    base = _git(root=product.parent, arguments=["rev-parse", "HEAD"]).strip()
    (product / "docs/receipts/files.txt").write_text("src/tracked.py\nsrc/deleted.py\n")
    script = _install_audit(product=product, base=base, source=AUDIT)
    result = _run_audit(product=product, script=script)
    assert result.returncode != 0
    assert "MISSING candidate path" in result.stdout
    assert "src/deleted.py" in result.stdout


def test_discovery_tests_reject_removed_tracked_enumeration(tmp_path: Path) -> None:
    """The discovery subject must be invisible to an audit without Git enumeration.

    Substituting ``changed = []`` for the real ``git diff --relative``
    enumeration (the sensitivity mutant, equivalent in effect to the
    root-relative path regression that silently empties it) must flip the
    untyped discovery case to green. The real audit still flags the same
    subject, so the pair of outcomes proves the discovery tests above depend
    on the tracked-discovery channel they claim to protect.
    """
    assert AUDIT.read_text().count(_TRACKED_ENUMERATION) == 1
    mutant = tmp_path / "audit-mutant.py"
    assert mutant.resolve().is_relative_to(tmp_path.resolve())
    mutant.write_text(AUDIT.read_text().replace(_TRACKED_ENUMERATION, "changed = []"))
    mutant_runs = tmp_path / "mutant-runs"
    mutant_runs.mkdir()
    assert mutant_runs.resolve().is_relative_to(tmp_path.resolve())
    mutant_result = _prepare_discovery_case(tmp_path=mutant_runs, annotated=False, source=mutant)
    assert mutant_result.returncode == 0, mutant_result.stdout + mutant_result.stderr
    assert "new_tracked_definition" not in mutant_result.stdout
    real_runs = tmp_path / "real-runs"
    real_runs.mkdir()
    assert real_runs.resolve().is_relative_to(tmp_path.resolve())
    real_result = _prepare_discovery_case(tmp_path=real_runs, annotated=False, source=AUDIT)
    assert real_result.returncode != 0
    assert "new_tracked_definition" in real_result.stdout
