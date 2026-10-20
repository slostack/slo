"""Read-only manifest and exact headless-annotation reconciliation."""

import hashlib
from pathlib import Path


def load_manifest(path: Path) -> dict[str, str]:
    """Read the retained product-relative SHA256 manifest."""
    return dict((line.split("  ", 1)[1], line.split("  ", 1)[0]) for line in path.read_text().splitlines())


def main() -> None:
    """Verify current inputs and reconstruct the prior headless bytes in memory."""
    root = Path("docs/implementation/94-herdr")
    previous = load_manifest(root / "gates-171-receipts/after.sha256")
    current = load_manifest(root / "turn6-code-test-174-receipts/after.sha256")
    mismatches = [name for name, digest in current.items() if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
    changed = [name for name in previous if current.get(name) != previous[name]]
    print("174 current manifest:", len(current), "mismatches:", mismatches)
    print("171 -> 174 changed:", changed)
    print("Added:", sorted(set(current) - set(previous)))
    print("Removed:", sorted(set(previous) - set(current)))
    core = [name for name in previous if name.startswith("src/agents/slo_agent/herdr/")]
    assert all(previous[name] == current[name] for name in core)
    print("Unchanged core production inputs:", len(core))
    assert not mismatches
    name = "tests/cli/test_headless.py"
    text = Path(name).read_text()
    substitutions = {
        'async def test_reporting_lifetime_surrounds_headless_run(\n    tmp_path: Path, terminal_kind: StreamEventKind\n) -> None:': 'async def test_reporting_lifetime_surrounds_headless_run(tmp_path, terminal_kind: StreamEventKind) -> None:',
        'async def test_activation_exit_restores_signal_owner(tmp_path: Path, cancel: bool) -> None:': 'async def test_activation_exit_restores_signal_owner(tmp_path, cancel: bool) -> None:',
        'async def test_adopted_setup_and_terminal_fault_restore_signal(tmp_path: Path, boundary: str) -> None:': 'async def test_adopted_setup_and_terminal_fault_restore_signal(tmp_path, boundary: str) -> None:',
    }
    for old, new in substitutions.items():
        assert text.count(old) == 1
        text = text.replace(old, new)
    digest = hashlib.sha256(text.encode()).hexdigest()
    print("Headless after reversing exactly three signature annotations/wrapping:", digest)
    print("171 headless:", previous[name])
    print("Exact prior bytes reconstructed:", digest == previous[name])


if __name__ == "__main__":
    main()
