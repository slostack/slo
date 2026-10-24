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
enumeration can reach it. ``_prepare_discovery_case`` asserts those channel
preconditions directly, the typed case asserts the audit actually examined
the subject (its ``Checked N`` count), and the missing-candidate case adds a
tracked-discovery missing candidate (a committed broken symlink), so every
discovery regression rejects the mutant that removes the tracked enumeration
instead of passing with the channel stripped.

Single source-under-test seam: the three ordinary regressions read the audit
source through the module-global ``AUDIT`` binding **and nowhere else**. The
``_REAL_AUDIT`` module-level binding below is a documented compatibility
target for the preserved residual probe only — it is never read by any
regression, so it cannot become a second un-patched source-under-test path.
The preserved independent
observation probe (``review-wiring-175-receipts/test_review_boundaries.py``)
monkeypatches exactly this global to a ``changed = []`` mutant and then calls
the regression functions, so its mutation now reaches the real source under
test; the probe remains an observation-of-survival (it prints the outcome, it
does not assert rejection). Genuine rejection lives in the explicitly
identified oracle ``test_regression_rejects_removed_tracked_discovery``,
which patches the same seam and *requires* each regression to raise.

Mutant separation: every real/mutant comparison is a separate test function
whose audit source is a materialized mutant — never a monkeypatched global —
so mutation can never silently fall back to an unmutated source:

- ``test_discovery_tests_reject_removed_tracked_enumeration`` contrasts the
  untyped subject under the ``changed = []`` mutant with the same subject
  under the removed-``--relative`` mutant (root-relative names that enumerate
  nothing the nested product cwd can stat), proving the two mutants are not
  treated as literally identical: one reports only the owned base definition
  while the other also reports every tracked subject as a MISSING candidate.
- ``test_missing_candidate_tests_reject_removed_tracked_enumeration`` does
  the same for the missing-candidate case, where the mutants differ again
  (the discovery-channel missing symlink is reported only without the
  tracked enumeration; both mutants still fail on the owned missing path).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

AUDIT = (
    Path(__file__).resolve().parents[2]
    / "docs/implementation/94-herdr/conventions-revision-159-receipts/audit.py"
)

_TRACKED_ENUMERATION = """changed = subprocess.check_output(
        ["git", "diff", "--relative", "--name-only", BASE, "--", "src", "tests"], text=True
    ).splitlines()"""

# Reviewer-probe compatibility binding. No test in this module reads it; it
# exists only so the preserved residual probe
# (``review-wiring-178-receipts/test_residuals.py``) can redirect it alongside
# ``AUDIT`` when contrasting the historical seam with both source bindings.
# The single source-under-test seam for every ordinary regression is the
# ``AUDIT`` global above; never read this alias from a regression.
_REAL_AUDIT = AUDIT

_RELATIVE_FLAG = '"--relative", '


def _write_sensitivity_mutant(*, tmp_path: Path, source: Path) -> Path:
    """Materialize the ``changed = []`` sensitivity mutant of one audit source.

    A source already stripped of the tracked enumeration (the sensitivity
    probe's monkeypatched mutant) is copied through unchanged; the mutant
    contract — no ``git diff --relative`` enumeration — is what the mutant
    half asserts, not the exact substitution that produced it.
    """
    text = source.read_text()
    assert text.count(_TRACKED_ENUMERATION) in (0, 1)
    mutant = tmp_path / "audit-mutant.py"
    assert mutant.resolve().is_relative_to(tmp_path.resolve())
    mutant.write_text(text.replace(_TRACKED_ENUMERATION, "changed = []"))
    return mutant


def _write_relative_removed_mutant(*, tmp_path: Path) -> Path:
    """Materialize the root-relative mutant: tracked enumeration without ``--relative``.

    From the nested product cwd, plain ``git diff --name-only`` emits
    repository-root-relative ``slo/...`` names that do not exist here, so the
    enumeration is non-empty yet every entry becomes a MISSING candidate.
    This mutant is deliberately distinct from the ``changed = []`` mutant:
    both strip usable tracked discovery, but their observable failures differ.
    """
    text = AUDIT.read_text()
    assert text.count(_TRACKED_ENUMERATION) == 1
    mutant = tmp_path / "audit-no-relative.py"
    assert mutant.resolve().is_relative_to(tmp_path.resolve())
    mutant.write_text(text.replace(_RELATIVE_FLAG, ""))
    return mutant


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
    assert _git(root=root, arguments=["status", "--porcelain"]) == ""
    assert root.resolve().is_relative_to(tmp_path.resolve())
    return product


def _install_audit(*, product: Path, base: str, source: Path) -> Path:
    """Place the audit script with the synthetic base commit patched in.

    The script lives under ``docs/``, outside the audit's own ``src`` /
    ``tests`` enumeration pathspecs, so its placement can never leak a
    discovery subject into the audited candidate set.
    """
    target = product / "docs/receipts/audit.py"
    text = source.read_text()
    patched = text.replace('BASE = "d0e3a756689f2675e5507034d43cd8b272d3c6b8"', f'BASE = "{base}"')
    patched = patched.replace(
        'ROOT = Path("docs/implementation/94-herdr/conventions-revision-159-receipts")',
        'ROOT = Path("docs/receipts")',
    )
    assert patched != text
    target.write_text(patched)
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


def _tracked_discovery_subject_body(*, annotated: bool) -> str:
    """Return the tracked-discovery subject source for one annotation state."""
    if annotated:
        return (
            "def new_tracked_definition(value: int) -> int:\n"
            '    """New tracked definition with complete annotations."""\n'
            "    return value\n"
        )
    return (
        "def new_tracked_definition(untyped):\n"
        '    """New tracked definition missing one annotation."""\n'
        "    return untyped\n"
    )


def _assert_tracked_discovery_channel(*, product: Path, base: str) -> None:
    """Prove the subject is reachable only through ``git diff --relative``."""
    # The audited src/ and tests/ trees are fully tracked; only the synthetic
    # audit placement under docs/ remains outside the index.
    assert _git(root=product.parent, arguments=["status", "--porcelain", "--", "slo/src", "slo/tests"]) == ""
    assert "src/tracked_after.py" not in (product / "docs/receipts/files.txt").read_text()
    others = _git(
        root=product,
        arguments=["ls-files", "--others", "--exclude-standard", "src", "tests"],
    )
    assert "src/tracked_after.py" not in others.splitlines()
    discovered = _git(
        root=product,
        arguments=["diff", "--relative", "--name-only", base, "--", "src", "tests"],
    )
    assert "src/tracked_after.py" in discovered.splitlines()


def _run_discovery_case(*, tmp_path: Path, annotated: bool, source: Path) -> subprocess.CompletedProcess[str]:
    """Run one audit source against the tracked-discovery subject, unasserted.

    The subject lives in ``src/tracked_after.py``, committed after the base
    commit, absent from ``files.txt`` and absent from the untracked set, so an
    audit can reach it only through ``git diff --relative``. The result is
    returned raw: each caller asserts the outcome its audit source must
    produce, so real-audit expectations and mutant-audit expectations never
    share one assertion set.
    """
    product = _init_nested_repo(tmp_path=tmp_path)
    base = _git(root=product.parent, arguments=["rev-parse", "HEAD"]).strip()
    (product / "src/tracked_after.py").write_text(_tracked_discovery_subject_body(annotated=annotated))
    _commit_all(root=product.parent, message="tracked addition")
    script = _install_audit(product=product, base=base, source=source)
    _assert_tracked_discovery_channel(product=product, base=base)
    return _run_audit(product=product, script=script)


def _assert_audit_flags_untyped_subject(result: subprocess.CompletedProcess[str]) -> None:
    """Assert the source under test flags and examines the untyped subject."""
    assert result.returncode != 0
    assert "src/tracked_after.py" in result.stdout
    assert "new_tracked_definition" in result.stdout
    # The owned base definition plus the Git-discovered untyped definition
    # make exactly two examined definitions; the failing flag is among them.
    assert "Checked 2 owned/new definitions" in result.stdout


def _assert_audit_accepts_annotated_subject(result: subprocess.CompletedProcess[str]) -> None:
    """Assert the source under test passes with the annotated subject examined."""
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MISSING" not in result.stdout
    # The owned base definition plus the Git-discovered annotated definition
    # make exactly two examined definitions.
    assert "Checked 2 owned/new definitions" in result.stdout


def test_audit_flags_new_tracked_definition_from_nested_product_cwd(tmp_path: Path) -> None:
    """A newly added tracked definition is discovered and checked from ``slo/``.

    The source under test — read through the patchable ``AUDIT`` global, the
    single audit-source seam — must flag the untyped subject with the
    examined-definition count proving it was checked. Real/mutant comparison
    lives in the separate ``test_discovery_tests_reject_removed_tracked_*``
    tests so a mutation of the ``AUDIT`` seam can never silently fall back to
    an unmutated source here.
    """
    result = _run_discovery_case(tmp_path=tmp_path, annotated=False, source=AUDIT)
    _assert_audit_flags_untyped_subject(result=result)


def test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd(tmp_path: Path) -> None:
    """A fully annotated newly added tracked definition leaves the audit green.

    The source under test must pass with the subject examined (the count
    proves the tracked enumeration found it and accepted its types); a
    green that never examined the subject cannot satisfy this contract.
    """
    result = _run_discovery_case(tmp_path=tmp_path, annotated=True, source=AUDIT)
    _assert_audit_accepts_annotated_subject(result=result)


def _prepare_missing_candidate_case(*, tmp_path: Path, source: Path) -> subprocess.CompletedProcess[str]:
    """Run one audit source against owned plus tracked-discovery missing candidates.

    ``src/deleted.py`` is an owned (``files.txt``) candidate that vanished
    from disk. ``src/broken_link.py`` is a tracked broken symlink committed
    after the base commit — explicitly asserted absent from ``files.txt``
    and from the untracked set — so only the ``git diff --relative``
    enumeration can reach it, and ``Path.is_file()`` is False for its
    dangling target.
    """
    product = _init_nested_repo(tmp_path=tmp_path)
    base = _git(root=product.parent, arguments=["rev-parse", "HEAD"]).strip()
    (product / "docs/receipts/files.txt").write_text("src/tracked.py\nsrc/deleted.py\n")
    # Relative dangling target inside the synthetic repo; never a system file.
    (product / "src/broken_link.py").symlink_to("missing_target.py")
    _commit_all(root=product.parent, message="tracked broken link")
    script = _install_audit(product=product, base=base, source=source)
    assert _git(root=product.parent, arguments=["status", "--porcelain", "--", "slo/src", "slo/tests"]) == ""
    assert "src/broken_link.py" not in (product / "docs/receipts/files.txt").read_text()
    others = _git(
        root=product,
        arguments=["ls-files", "--others", "--exclude-standard", "src", "tests"],
    )
    assert "src/broken_link.py" not in others.splitlines()
    discovered = _git(
        root=product,
        arguments=["diff", "--relative", "--name-only", base, "--", "src", "tests"],
    )
    assert "src/broken_link.py" in discovered.splitlines()
    return _run_audit(product=product, script=script)


def test_audit_fails_on_missing_candidate_path(tmp_path: Path) -> None:
    """Missing candidates fail instead of being skipped, on both channels.

    The owned missing candidate is preserved unchanged. The source under
    test must also report the tracked-discovery missing candidate, and both
    missing reports must come from the same run whose examined count covers
    only the remaining owned base definition.
    """
    result = _prepare_missing_candidate_case(tmp_path=tmp_path, source=AUDIT)
    assert result.returncode != 0
    assert "MISSING candidate path" in result.stdout
    assert "src/deleted.py" in result.stdout
    assert "src/broken_link.py" in result.stdout
    # Only the owned base definition is examined; both missing candidates
    # must be reported by the same run.
    assert "Checked 1 owned/new definitions" in result.stdout


def test_regression_rejects_removed_tracked_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REJECTION ORACLE: each ordinary regression must fail under ``changed = []``.

    The preserved observation probe patches the ``AUDIT`` global and only
    *prints* whether a regression survived. This oracle patches the same
    seam and requires the opposite: with the tracked enumeration removed
    from the source under test, every ordinary regression must raise —
    genuine mutant rejection at the real seam, not survival.
    """
    mutant = _write_sensitivity_mutant(tmp_path=tmp_path, source=AUDIT)
    # Patch the *running* module object by identity: a dotted-string target
    # could resolve to a second module instance (pytest's import name for a
    # rootless test tree differs from the package path), silently missing the
    # seam this oracle exists to exercise.
    monkeypatch.setattr(target=sys.modules[__name__], name="AUDIT", value=mutant)
    cases = [
        test_audit_flags_new_tracked_definition_from_nested_product_cwd,
        test_audit_passes_annotated_new_tracked_definition_from_nested_product_cwd,
        test_audit_fails_on_missing_candidate_path,
    ]
    for index, regression in enumerate(cases):
        case_root = tmp_path / f"case-{index}"
        case_root.mkdir()
        assert case_root.resolve().is_relative_to(tmp_path.resolve())
        with pytest.raises(AssertionError):
            regression(tmp_path=case_root)


def test_discovery_tests_reject_removed_tracked_enumeration(tmp_path: Path) -> None:
    """The untyped subject separates removed enumeration from removed ``--relative``.

    Under the ``changed = []`` mutant the subject is simply invisible. Under
    the removed-``--relative`` mutant the enumeration yields
    repository-root-relative names that do not exist from the nested product
    cwd, so the repaired missing-path behavior reports them as MISSING — the
    two mutants are not literally identical, and both are rejected by the
    ordinary regressions' real-audit expectations.
    """
    empty_mutant = _write_sensitivity_mutant(tmp_path=tmp_path, source=AUDIT)
    empty_runs = tmp_path / "empty-runs"
    empty_runs.mkdir()
    assert empty_runs.resolve().is_relative_to(tmp_path.resolve())
    empty_result = _run_discovery_case(tmp_path=empty_runs, annotated=False, source=empty_mutant)
    assert empty_result.returncode == 0, empty_result.stdout + empty_result.stderr
    assert "src/tracked_after.py" not in empty_result.stdout
    assert "new_tracked_definition" not in empty_result.stdout
    # Only the owned base definition is examined once discovery is removed.
    assert "Checked 1 owned/new definitions" in empty_result.stdout

    relative_mutant = _write_relative_removed_mutant(tmp_path=tmp_path)
    relative_runs = tmp_path / "relative-runs"
    relative_runs.mkdir()
    assert relative_runs.resolve().is_relative_to(tmp_path.resolve())
    relative_result = _run_discovery_case(tmp_path=relative_runs, annotated=False, source=relative_mutant)
    assert relative_result.returncode != 0
    assert "MISSING candidate path" in relative_result.stdout
    # Root-relative names do not exist from the nested product cwd.
    assert "slo/src/tracked_after.py" in relative_result.stdout
    assert "new_tracked_definition" not in relative_result.stdout
    assert "Checked 1 owned/new definitions" in relative_result.stdout


def test_missing_candidate_tests_reject_removed_tracked_enumeration(tmp_path: Path) -> None:
    """The missing-candidate case separates the two discovery-loss mutants.

    Both mutants still fail on the owned missing ``src/deleted.py`` path —
    the repaired audit never skips a missing candidate — but the
    tracked-discovery missing symlink is reported only by the mutant that
    keeps enumerating (without ``--relative``), not by the one with no
    enumeration at all.
    """
    empty_mutant = _write_sensitivity_mutant(tmp_path=tmp_path, source=AUDIT)
    empty_runs = tmp_path / "empty-runs"
    empty_runs.mkdir()
    assert empty_runs.resolve().is_relative_to(tmp_path.resolve())
    empty_result = _prepare_missing_candidate_case(tmp_path=empty_runs, source=empty_mutant)
    assert empty_result.returncode != 0
    assert "MISSING candidate path" in empty_result.stdout
    assert "src/deleted.py" in empty_result.stdout
    assert "src/broken_link.py" not in empty_result.stdout
    assert "Checked 1 owned/new definitions" in empty_result.stdout

    relative_mutant = _write_relative_removed_mutant(tmp_path=tmp_path)
    relative_runs = tmp_path / "relative-runs"
    relative_runs.mkdir()
    assert relative_runs.resolve().is_relative_to(tmp_path.resolve())
    relative_result = _prepare_missing_candidate_case(tmp_path=relative_runs, source=relative_mutant)
    assert relative_result.returncode != 0
    assert "MISSING candidate path" in relative_result.stdout
    assert "src/deleted.py" in relative_result.stdout
    assert "slo/src/broken_link.py" in relative_result.stdout
    assert "Checked 1 owned/new definitions" in relative_result.stdout
