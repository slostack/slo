"""Contracts for canonical specification authoring and design guidance."""

from pathlib import Path
import re

import pytest

from scripts import build_skill_index
from scripts.build_skill_index import _INDEX_HEADER
from src.agents.skills.registry import SkillRegistry
from src.agents.slo_agent.skills.service import SkillsLoader

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


def test_module_depth_guidance_preserves_hard_rules_and_language_boundaries() -> None:
    """Keep depth advisory without weakening extraction or required adapters."""
    text = (SKILLS_DIR / "coding/declarative-method-structure/SKILL.md").read_text(encoding="utf-8")
    assert "## Module-depth design guidance" in text
    for requirement in (
        "constructors",
        "cancellation",
        "durability",
        "Python",
        "Go",
        "TypeScript",
        "one `invoke`",
        "not an automatic review blocker",
        "~8 lines of logic",
        "CLI adapters",
        "agent-tool bridges",
        "cohesive private helpers",
    ):
        assert requirement in text


def test_overview_author_has_ordered_procedure_and_document() -> None:
    """The overview author gathers context before writing and orders the document for the reader."""
    text = (SKILLS_DIR / "design-and-analysis/feature-specifications/SKILL.md").read_text(encoding="utf-8")
    procedure = (
        "## Artifact paths and skill discovery",
        "## Inputs",
        "## Mandatory first task: establish knowledge-base context",
        "## Read before writing",
        "## Duplicate-code check",
        "## Cohesion over line-level DRY",
        "## The document",
        "## Before saving",
    )
    positions = [text.index(section) for section in procedure]
    assert positions == sorted(positions)
    document = (
        "**What this feature does.**",
        "**Domains and data.**",
        "**Journeys and workflows.**",
        "**Modules, interfaces and caller use.**",
        "**Tests, limits and next steps.**",
    )
    positions = [text.index(section) for section in document]
    assert positions == sorted(positions)
    for requirement in (
        "overview.md",
        "standalone engineering sub-specs",
        "breakdown-feature-spec-to-tasks",
        "feature-specification-verification",
        "gather-feature-context",
        "The deletion test, verbatim",
        "Open decisions",
        "one vertical piece of functionality end to end",
    ):
        assert requirement in text

def test_legacy_hooks_are_removed_and_unreferenced() -> None:
    """The overview author replaced the PRE/POST hooks; nothing may route to them."""
    for hook in ("pre", "post"):
        assert not (SKILLS_DIR / f"design-and-analysis/feature-specifications-{hook}-hook").exists()
    for path in SKILLS_DIR.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for hook in ("feature-specifications-pre-hook", "feature-specifications-post-hook"):
            assert hook not in text, (path, hook)

def test_workflow_sequences_overview_sub_specs_then_family_review() -> None:
    """Both documents exist before one independent review, and REVISE returns to the owner."""
    path = SKILLS_DIR / "orchestration/workflows/specification-development.md"
    text = path.read_text(encoding="utf-8")
    steps = (
        "### Step 1 — Overview",
        "### Step 2 — Standalone engineering sub-specs",
        "### Step 3 — Family verification",
    )
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    owners = (
        "skills/design-and-analysis/feature-specifications/SKILL.md",
        "skills/design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md",
        "skills/design-and-analysis/feature-specification-verification/SKILL.md",
    )
    positions = [text.index(owner) for owner in owners]
    assert positions == sorted(positions)
    assert "independent, adversarial review" in text
    assert "`overview.md` → Step 1; sub-specs and `task-list.md` → Step 2" in text
    assert "#progression-and-authorization" in text
    for obsolete in ("pre-hook", "post-hook", "Self-check stage", "Gather context", "JIRA", "Mode A", "Mode B"):
        assert obsolete not in text, obsolete

def test_code_review_links_canonical_depth_guidance() -> None:
    """Make caller burden an evidence-based review concern in all languages."""
    text = (SKILLS_DIR / "design-and-analysis/review-feature-code/SKILL.md").read_text(encoding="utf-8")
    assert "#module-depth-design-guidance" in text
    assert "constructors, ordering, flags and errors" in text
    assert "not an automatic blocker" in text


def test_refresh_preserves_repository_owned_authoring_and_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing the authored tree cannot rewrite local authoring or workflow policy."""
    skills_dir = tmp_path / "skills"
    author = skills_dir / "design-and-analysis/feature-specifications/SKILL.md"
    workflow = skills_dir / "orchestration/workflows/specification-development.md"
    author.parent.mkdir(parents=True)
    workflow.parent.mkdir(parents=True)
    author.write_text("canonical author", encoding="utf-8")
    workflow.write_text("local workflow", encoding="utf-8")
    monkeypatch.setattr(build_skill_index, "_resolve_skills_dir", lambda: skills_dir)

    assert build_skill_index.main() == 0
    assert author.read_text(encoding="utf-8") == "canonical author"
    assert workflow.read_text(encoding="utf-8") == "local workflow"
    assert (skills_dir / "INDEX.md").is_file()


def test_refresh_preserves_authored_resources_and_discovers_nested_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing the index preserves authored resources and discovers families recursively."""
    skills_dir = tmp_path / "skills"
    authored = {
        "languages/go/go-conventions/SKILL.md": (
            "---\nname: go-conventions\ndescription: Go guidance.\n"
            "when_to_use: Use for Go.\ngroup: languages\nkind: skill\n---\nGo body.\n"
        ),
        "engineering/testing/SKILL.md": (
            "---\nname: testing\ndescription: Test guidance.\n"
            "when_to_use: Use for tests.\ngroup: engineering\nkind: skill\n---\nTest body.\n"
        ),
        "presentation/pdf/assets/style.css": "body { color: navy; }\n",
        "samples/example.md": "# Sample\n",
    }
    for relative, content in authored.items():
        destination = skills_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    monkeypatch.setattr(build_skill_index, "_resolve_skills_dir", lambda: skills_dir)

    before = {relative: (skills_dir / relative).read_bytes() for relative in authored}
    assert build_skill_index.main() == 0
    after = {relative: (skills_dir / relative).read_bytes() for relative in authored}

    assert after == before
    index = (skills_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "skills/languages/go/go-conventions/SKILL.md" in index
    assert "skills/engineering/testing/SKILL.md" in index


def test_refresh_rebuilds_index_for_new_authored_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresh command's delegated builder indexes a new authored skill."""
    skills_dir = tmp_path / "skills"
    destination = skills_dir / "coding/example/SKILL.md"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        "---\nname: example\ndescription: Example guidance.\n"
        "when_to_use: Use for examples.\ngroup: coding\nkind: skill\n---\nExample body.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(build_skill_index, "_resolve_skills_dir", lambda: skills_dir)

    assert build_skill_index.main() == 0
    index = (skills_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "**example**" in index
    assert "skills/coding/example/SKILL.md" in index


def test_context_companion_metadata_and_paths_use_canonical_author() -> None:
    """Discovery must describe an optional on-request companion that feeds the overview author."""
    registry = next(
        skill for skill in SkillRegistry.load(skills_dir=SKILLS_DIR) if skill.name == "gather-feature-context"
    )
    runtime = next(
        skill for skill in SkillsLoader.load(skills_dir=str(SKILLS_DIR)) if skill.name == registry.name
    )
    assert runtime.description == registry.description
    for description in (runtime.description, registry.when_to_use):
        assert "on-request" in description.lower()
        assert "feature-specifications" in description
        assert "Gather context" not in description
        assert not description.lower().startswith("pre-hook")
    text = (SKILLS_DIR / "design-and-analysis/gather-feature-context/SKILL.md").read_text(encoding="utf-8")
    assert "../feature-specifications/SKILL.md#artifact-paths-and-skill-discovery" in text
    assert "../feature-specifications/SKILL.md#inputs" in text
    assert "SLO_FEATURE_SPECIFICATIONS_DIR" not in text
    assert "This pre-hook" not in text
    assert "Stop here and wait for user sign-off" in text

def test_convention_lists_cover_each_language_and_resolve() -> None:
    """Both authors route to Python, Go and TypeScript conventions through real skill paths."""
    for relative in (
        "design-and-analysis/feature-specifications/SKILL.md",
        "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md",
    ):
        text = (SKILLS_DIR / relative).read_text(encoding="utf-8")
        for gateway in (
            "languages/python/python-conventions/SKILL.md",
            "languages/go/go-conventions/SKILL.md",
            "languages/typescript/typescript-conventions/SKILL.md",
            "coding/test-verification-policy/SKILL.md",
        ):
            assert gateway in text, (relative, gateway)
    text = (SKILLS_DIR / "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md").read_text(encoding="utf-8")
    section = text.split("#### Convention skills by language and layer", 1)[1].split("\n### ", 1)[0]
    roots = ("", "languages/python/", "languages/go/", "languages/typescript/")
    for reference in re.findall(pattern=r"`([a-z0-9/-]+/SKILL\.md)`", string=section):
        assert any((SKILLS_DIR / f"{root}{reference}").is_file() for root in roots), reference


def test_specification_skills_keep_dry_with_cohesion() -> None:
    """Every specification skill demands consolidation without extracting a flush from its write."""
    for relative in (
        "design-and-analysis/feature-specifications/SKILL.md",
        "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md",
        "design-and-analysis/feature-specification-verification/SKILL.md",
    ):
        text = (SKILLS_DIR / relative).read_text(encoding="utf-8")
        assert "No existing owner found" in text or "none exists" in text, relative
        assert "await db_session.flush()" in text, relative
        assert "autocommit" not in text, relative
        assert "owns the commit" in text, relative


def test_specification_skills_prioritise_behaviour_tests_without_tool_specific_sources() -> None:
    """Behaviour tests lead, unit tests cover complex computation, and sources are tool-neutral."""
    for relative in (
        "design-and-analysis/feature-specifications/SKILL.md",
        "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md",
        "design-and-analysis/feature-specification-verification/SKILL.md",
    ):
        text = (SKILLS_DIR / relative).read_text(encoding="utf-8")
        assert "complex computation" in text, relative
        assert "Playwright" in text, relative
        assert "JIRA" not in text and "Jira" not in text, relative

def test_generated_index_matches_registry() -> None:
    """Verify generated discovery metadata rather than hand-maintained keywords."""
    expected = _INDEX_HEADER + SkillRegistry.format_for_prompt(
        skills=SkillRegistry.load(skills_dir=SKILLS_DIR)
    )
    assert (SKILLS_DIR / "INDEX.md").read_text(encoding="utf-8") == expected


def test_authoring_relative_links_and_anchors_resolve() -> None:
    """Check canonical links and compatibility destinations in shipped Markdown."""
    paths = list((SKILLS_DIR / "design-and-analysis").glob("feature-spec*/SKILL.md"))
    paths.extend(
        SKILLS_DIR / relative
        for relative in (
            "design-and-analysis/review-feature-code/SKILL.md",
            "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md",
            "design-and-analysis/gather-feature-context/SKILL.md",
            "design-and-analysis/specification-development/SKILL.md",
            "orchestration/workflows/SKILL.md",
            "orchestration/workflows/specification-development.md",
            "design-and-analysis/implement-feature-request/SKILL.md",
            "orchestration/orchestrator/SKILL.md",
            "orientation/readme/SKILL.md",
            "coding/declarative-method-structure/SKILL.md",
        )
    )
    for path in paths:
        # Links inside fenced blocks are document templates, not live references.
        text = re.sub(pattern=r"^```.*?^```", repl="", string=path.read_text(encoding="utf-8"), flags=re.MULTILINE | re.DOTALL)
        for target in re.findall(pattern=r"\]\(([^)]+)\)", string=text):
            if "://" in target:
                continue
            filename, _, anchor = target.partition("#")
            destination = (path.parent / filename).resolve() if filename else path
            assert destination.is_file(), (path, target)
            if anchor:
                headings = re.findall(
                    pattern=r"^#{1,6} (.+)$",
                    string=destination.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                anchors = {
                    re.sub(pattern=r"[^\w\- ]", repl="", string=heading.lower()).replace(" ", "-")
                    for heading in headings
                }
                assert anchor in anchors, (path, target)


def test_specification_family_has_no_mode_selection_or_partial_exceptions() -> None:
    """Keep authoring, independent review and breakdown on the same two-part contract."""
    paths = (
        "design-and-analysis/feature-specifications/SKILL.md",
        "design-and-analysis/feature-specification-verification/SKILL.md",
        "design-and-analysis/breakdown-feature-spec-to-tasks/SKILL.md",
        "orchestration/workflows/specification-development.md",
    )
    for relative in paths:
        text = (SKILLS_DIR / relative).read_text(encoding="utf-8")
        assert "overview.md" in text, relative
        assert "standalone engineering sub-specs" in text, relative
        for obsolete in (
            "Mode A",
            "Mode B",
            "mode-aware",
            "spec-mode",
            "spec mode",
            "chosen mode",
            "for its mode",
            "overview only",
            "tiny combined-document exception",
            "may fold both halves",
            "unless explicitly scoped otherwise",
        ):
            assert obsolete not in text, (relative, obsolete)


def test_skill_locations_follow_runtime_discovery_not_install_layout() -> None:
    """Keep instructions portable across installed packages and developer checkouts."""
    text = (SKILLS_DIR / "design-and-analysis/feature-specifications/SKILL.md").read_text(encoding="utf-8")
    for reference in (
        "SLO_SKILLS_DIR",
        "SLO_HOME",
        "SLO_USER_SKILLS_DIR",
        "SLO_USER_WORKFLOWS_DIR",
        "config.cfg",
        "file_path",
        "package-adjacent",
    ):
        assert reference in text
    for relative in (
        "design-and-analysis/feature-specifications/SKILL.md",
        "orientation/readme/SKILL.md",
    ):
        content = (SKILLS_DIR / relative).read_text(encoding="utf-8")
        for assumed_path in (
            "/root/",
            "/Users/",
            "/home/",
            "site-packages/",
            "~/.slo/user_skills",
            "~/.slo/user_workflows",
        ):
            assert assumed_path not in content, (relative, assumed_path)


def test_packaged_granularity_example_does_not_reintroduce_spec_modes() -> None:
    """The authoring reference example must use the mandatory family vocabulary."""
    text = (SKILLS_DIR / "samples/implementation-details-granularity.md").read_text(encoding="utf-8")
    assert "Mode B" not in text
    assert "Spec mode" not in text
    assert "**Artifact:**" in text
    for prefix in ("/root/", "/Users/", "/home/"):
        assert prefix not in text
