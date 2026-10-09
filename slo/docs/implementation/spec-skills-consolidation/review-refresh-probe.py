"""Review-only reproduction of refresh behavior in an owned temporary directory."""

from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.refresh_skills import _build_skill_specs, _write_skills


def main() -> None:
    """Show whether upstream refresh preserves the existing workflow pointer."""
    application_root = Path.cwd().resolve()
    evidence_root = application_root / "docs/implementation/spec-skills-consolidation"
    original = application_root / "skills/design-and-analysis/code-test-review/SKILL.md"
    workflow = application_root / "skills/design-and-analysis/workflows/code-test-review.md"
    with TemporaryDirectory(prefix="review-refresh-", dir=evidence_root) as directory:
        temporary_root = Path(directory).resolve()
        destination = temporary_root / "skills/design-and-analysis/code-test-review/SKILL.md"
        upstream = temporary_root / "upstream/workflows/code-test-review.md"
        assert destination.resolve().is_relative_to(temporary_root)
        assert upstream.resolve().is_relative_to(temporary_root)
        destination.parent.mkdir(parents=True)
        upstream.parent.mkdir(parents=True)
        destination.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
        upstream.write_text(workflow.read_text(encoding="utf-8"), encoding="utf-8")
        specs = _build_skill_specs(prompts_root=temporary_root / "upstream", skills_dir=temporary_root / "skills")
        selected = specs["code-test-review"]
        print(f"Manifest source: {selected.source_rel}; output group: {selected.group}")
        _write_skills(specs={selected.slug: selected}, prompts_root=temporary_root / "upstream", skills_dir=temporary_root / "skills")
        after = destination.read_text(encoding="utf-8")
        print(f"Pointer preserved byte-for-byte: {after == original.read_text(encoding='utf-8')}")
        print(f"Pointer-only guidance remains: {'This index entry is a pointer.' in after}")
        print(f"Workflow procedure copied into SKILL.md: {'### Step 2 — Code Review' in after}")
        print("Source checkout files were read only; all writes were inside the owned temporary root.")


if __name__ == "__main__":
    main()
