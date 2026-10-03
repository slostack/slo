"""Feature 87 preservation, discovery and workflow contract regression tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from src.agents.skills.registry import SkillRegistry
from src.agents.slo_agent.skills.service import SkillsLoader

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"


def test_source_inventory_has_live_destinations() -> None:
    inventory = json.loads((ROOT / "docs/skills-reorganization/inventory.json").read_text())
    for item in inventory:
        if item["tier"] == "project-reference":
            continue
        assert item["status"] != "pending", item["source"]
        assert item["destination"], item["source"]
        assert (ROOT / item["destination"]).is_file(), item["source"]


def test_canonical_language_families_are_discoverable() -> None:
    entries = SkillsLoader.load(skills_dir=str(SKILLS))
    names = [entry.name for entry in entries]
    assert len(names) == len(set(names))
    for name in (
        "engineering-routing",
        "engineering-testing",
        "engineering-review",
        "python-conventions",
        "go-conventions",
        "typescript-conventions",
        "go-test-lifecycle",
        "go-build-application-services",
    ):
        assert name in names
    for language in ("python", "go", "typescript"):
        assert list((SKILLS / "languages" / language).rglob("SKILL.md"))


def test_routing_contract_covers_positive_and_negative_scenarios() -> None:
    text = (SKILLS / "engineering/engineering-routing/SKILL.md").read_text()
    for phrase in (
        "Go lifecycle",
        "FastAPI",
        "Vue composable",
        "mixed",
        "unsupported",
        "orchestration",
        "Gin",
        "PostgreSQL",
        "user",
        "override",
    ):
        assert phrase in text
    scenarios = json.loads((ROOT / "docs/skills-reorganization/routing-scenarios.json").read_text())
    assert len(scenarios) >= 5
    for case in scenarios:
        for path in case["required"]:
            assert (ROOT / path).is_file(), case["request"]
        assert not set(case["required"]) & set(case["excluded"])


def test_concrete_skill_references_resolve() -> None:
    pattern = re.compile(r"(?<![/\w])skills/[A-Za-z0-9_./-]+(?:SKILL\.md|workflows/[A-Za-z0-9_-]+\.md)")
    for path in SKILLS.rglob("*.md"):
        for reference in pattern.findall(path.read_text()):
            assert (ROOT / reference).is_file(), (path, reference)


def test_go_canonical_skills_do_not_collide_with_imported_legacy_names() -> None:
    inventory = json.loads((ROOT / "docs/skills-reorganization/inventory.json").read_text())
    legacy = {row.get("name") for row in inventory if row["tier"] == "installed-user"}
    for path in (SKILLS / "languages/go").rglob("SKILL.md"):
        meta = yaml.safe_load(path.read_text().split("---", 2)[1])
        assert meta["name"] not in legacy
        assert "Go" in meta["description"] or "go" in meta["description"]


def test_shared_workflow_routes_without_python_commands() -> None:
    for name in ("code-test-review", "gitlab-code-test-review"):
        text = (SKILLS / f"design-and-analysis/workflows/{name}.md").read_text()
        assert "engineering-routing" in text
        assert "engineering-testing" in text
        assert "poetry run pytest" not in text
        assert "Step 1" in text and "Step 2" in text and "Step 3" in text
        assert "READY" in text


def test_registry_and_runtime_catalog_agree_except_forwarders() -> None:
    registered = SkillRegistry.load(skills_dir=SKILLS)
    runtime = SkillsLoader.load(skills_dir=str(SKILLS))
    active = {entry.name for entry in runtime}
    for entry in registered:
        meta = yaml.safe_load((ROOT / entry.location).read_text().split("---", 2)[1])
        assert (entry.name in active) == (meta.get("disable-model-invocation") is not True)


def test_index_is_reproducible() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("skill_index", ROOT / "scripts/build_skill_index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = module._INDEX_HEADER + SkillRegistry.format_for_prompt(
        skills=SkillRegistry.load(skills_dir=SKILLS)
    )
    assert (SKILLS / "INDEX.md").read_text() == expected


def test_python_and_vue_recipe_sections_are_preserved() -> None:
    inventory = json.loads((ROOT / "docs/skills-reorganization/inventory.json").read_text())
    for row in inventory:
        if row["tier"] != "bundled":
            continue
        if not row["source"].startswith(("coding/", "frontend-vue/")):
            continue
        text = (ROOT / row["destination"]).read_text()
        for heading in row["headings"]:
            if heading == "## Section 1 — Universal Rules (all stacks, always)":
                heading = "## Section 1 — Python Rules"
            assert heading in text, (row["source"], heading)


def test_relative_markdown_skill_links_resolve() -> None:
    for path in SKILLS.rglob("*.md"):
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            if any(character in target for character in "<>{} "):
                continue
            file = target.split("#")[0]
            if file.endswith(".md"):
                assert (path.parent / file).is_file(), (path, target)


def test_canonical_go_root_survives_old_user_override(tmp_path: Path) -> None:
    user = tmp_path / "user/golang-coding-conventions"
    user.mkdir(parents=True)
    (user / "SKILL.md").write_text(
        "---\nname: golang-coding-conventions\ndescription: Old installed Go guidance\n---\n"
    )
    entries = SkillsLoader.load_merged(
        vendored_skills_dir=str(SKILLS),
        user_skills_dir=str(user.parent),
        user_workflows_dir=str(tmp_path / "missing"),
    )
    locations = {entry.name: entry.file_path for entry in entries}
    assert locations["go-conventions"] == str(SKILLS / "languages/go/go-conventions/SKILL.md")
    assert locations["golang-coding-conventions"] == str(user / "SKILL.md")
