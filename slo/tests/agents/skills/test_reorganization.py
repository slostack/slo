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
    duplicate_names = {name for name in names if names.count(name) > 1}
    assert duplicate_names == set()
    assert names.count("api-response-conventions") == 1
    assert names.count("python-api-response-conventions") == 1
    for name in (
        "engineering-routing",
        "engineering-testing",
        "engineering-review",
        "python-conventions",
        "go-conventions",
        "typescript-conventions",
        "go-test-lifecycle",
        "go-build-application-services",
        "python-declarative-method-structure",
        "go-declarative-method-structure",
        "typescript-declarative-method-structure",
        "build-sse-endpoints",
        "typescript-build-langgraph",
    ):
        assert name in names
    for language in ("python", "go", "typescript"):
        assert list((SKILLS / "languages" / language).rglob("SKILL.md"))


def test_final_tree_has_no_obsolete_forwarder_identities_or_paths() -> None:
    """Deleted redirects do not survive in authored files or the generated index."""
    deleted_slugs = (
        "application-structure",
        "auth-security-patterns",
        "bootstrap-project-scaffolding",
        "build-agent-tools",
        "build-api-documentation",
        "build-application-services",
        "build-celery-workers",
        "build-clickhouse-features",
        "build-clients",
        "build-dbos-workflow-orchestration-pattern",
        "build-domain-features",
        "build-event-handlers",
        "build-middleware",
        "build-partitioned-events",
        "build-react-agent-with-langgraph",
        "build-routers",
        "build-schedulers-tasks-with-dbos",
        "build-tcp-codec",
        "build-vscode-launch-configurations",
        "code-review-rules",
        "create-frontend-htmx-jinja2-fastapi-app",
        "generate-swagger-documentation",
        "graph-gateway-invoke-convention",
        "method-docstrings",
        "named-arguments-and-type-hints",
        "python-path-and-import-resolution",
        "setup-dependencies-and-tests",
        "switch-environments-and-run-tests",
        "test-app-services",
        "test-controllers",
        "test-domain-services",
        "test-graphs-and-agents",
    )
    index = (SKILLS / "INDEX.md").read_text(encoding="utf-8")
    authored_markdown = "\\n".join(
        path.read_text(encoding="utf-8") for path in SKILLS.rglob("*.md") if path.name != "INDEX.md"
    )
    for slug in deleted_slugs:
        assert not (SKILLS / "coding" / slug / "SKILL.md").exists(), slug
        assert f"legacy-{slug}" not in index
        assert f"skills/coding/{slug}/SKILL.md" not in authored_markdown
    assert "legacy-declarative-method-structure" not in index


def test_merged_loader_with_empty_user_tiers_retains_every_vendored_entry(tmp_path: Path) -> None:
    """Empty user directories do not hide or drop any active vendored entry."""
    user_skills = tmp_path / "user_skills"
    user_workflows = tmp_path / "user_workflows"
    user_skills.mkdir()
    user_workflows.mkdir()

    vendored = SkillsLoader.load(skills_dir=str(SKILLS))
    merged = SkillsLoader.load_merged(
        vendored_skills_dir=str(SKILLS),
        user_skills_dir=str(user_skills),
        user_workflows_dir=str(user_workflows),
    )

    assert [(entry.name, entry.file_path) for entry in merged] == [
        (entry.name, entry.file_path) for entry in vendored
    ]
    assert len({entry.name for entry in merged}) == len(merged)


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
        text = (SKILLS / f"orchestration/workflows/{name}.md").read_text()
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
            if row["source"] == "coding/declarative-method-structure/SKILL.md":
                continue
            if row["source"] == "coding/test-verification-policy/SKILL.md" and heading == "### Example":
                continue
            if row["source"] == "coding/naming-and-clarity/SKILL.md" and heading in {
                "### `Create…` / `Save…`",
                "### `BuildAndCreate…`",
                "### Idiomatic Go `newX`",
            }:
                continue
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


def test_api_response_identity_merge_and_user_override_isolation(tmp_path: Path) -> None:
    """Merged runtime entries keep both API-response identities and isolate overrides."""
    user_skills = tmp_path / "user_skills"
    user_workflows = tmp_path / "user_workflows"
    user_skills.mkdir()
    user_workflows.mkdir()

    entries = SkillsLoader.load_merged(
        vendored_skills_dir=str(SKILLS),
        user_skills_dir=str(user_skills),
        user_workflows_dir=str(user_workflows),
    )
    locations = {entry.name: entry.file_path for entry in entries}

    assert locations["api-response-conventions"] == str(SKILLS / "coding/api-response-conventions/SKILL.md")
    assert locations["python-api-response-conventions"] == str(
        SKILLS / "languages/python/api-response-conventions/SKILL.md"
    )
    assert (
        len(
            [
                entry
                for entry in entries
                if entry.name in {"api-response-conventions", "python-api-response-conventions"}
            ]
        )
        == 2
    )

    override = user_skills / "python-api-response-conventions" / "SKILL.md"
    override.parent.mkdir()
    override.write_text(
        "---\nname: python-api-response-conventions\ndescription: User override\n---\n",
        encoding="utf-8",
    )
    overridden = SkillsLoader.load_merged(
        vendored_skills_dir=str(SKILLS),
        user_skills_dir=str(user_skills),
        user_workflows_dir=str(user_workflows),
    )
    overridden_locations = {entry.name: entry.file_path for entry in overridden}

    assert overridden_locations["api-response-conventions"] == str(
        SKILLS / "coding/api-response-conventions/SKILL.md"
    )
    assert overridden_locations["python-api-response-conventions"] == str(override)
    assert len(overridden_locations) == len(overridden)


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


def test_selected_generic_skills_have_unique_active_runtime_identities() -> None:
    """The three focused generic skills remain active once each with no obsolete identity."""
    selected = {"code-test-loop", "naming-and-clarity", "test-verification-policy"}
    registered = SkillRegistry.load(skills_dir=SKILLS)
    runtime = SkillsLoader.load(skills_dir=str(SKILLS))
    runtime_names = [entry.name for entry in runtime]

    assert all(runtime_names.count(name) == 1 for name in selected)
    for entry in registered:
        if entry.name not in selected:
            continue
        metadata = yaml.safe_load((ROOT / entry.location).read_text().split("---", 2)[1])
        assert metadata.get("disable-model-invocation") is not True
        assert not entry.name.startswith("legacy-")


def test_generic_coding_rules_remains_the_sole_owner_of_the_sixteen_broad_principles() -> None:
    """Focused generic skills link to the broad owner instead of copying its principles."""
    source = (ROOT / "skills/coding/coding-rules/SKILL.md").read_text()
    broad_headings = tuple(re.findall(r"^\d+\. ([^.]+\.)", source, flags=re.MULTILINE))
    assert len(broad_headings) == 16

    for path in (
        SKILLS / "coding/code-test-loop/SKILL.md",
        SKILLS / "coding/naming-and-clarity/SKILL.md",
        SKILLS / "coding/test-verification-policy/SKILL.md",
    ):
        text = path.read_text()
        assert not all(heading in text for heading in broad_headings)


def test_declarative_owner_and_language_specializations_are_unique_and_linked() -> None:
    """The generic owner and three language recipes form one explicit ownership chain."""
    generic = SKILLS / "coding/declarative-method-structure/SKILL.md"
    paths = {
        "python": SKILLS / "languages/python/declarative-method-structure/SKILL.md",
        "go": SKILLS / "languages/go/go-declarative-method-structure/SKILL.md",
        "typescript": SKILLS / "languages/typescript/typescript-declarative-method-structure/SKILL.md",
    }
    generic_text = generic.read_text(encoding="utf-8")
    assert "full language-independent owner" in generic_text
    assert "core-coding-rules.md" in generic_text
    for language, path in paths.items():
        text = path.read_text(encoding="utf-8")
        assert "skills/coding/declarative-method-structure/SKILL.md" in text
        assert language.capitalize() in text or language == "typescript"
        assert "specialization" in text.lower()
    entries = SkillsLoader.load(skills_dir=str(SKILLS))
    assert [entry.name for entry in entries].count("declarative-method-structure") == 1
    assert [entry.name for entry in entries].count("python-declarative-method-structure") == 1
    assert [entry.name for entry in entries].count("go-declarative-method-structure") == 1
    assert [entry.name for entry in entries].count("typescript-declarative-method-structure") == 1


def test_language_specific_verification_requirements_remain_in_language_owners() -> None:
    """Generic verification wording does not erase Go ordering or TypeScript build gates."""
    generic = (SKILLS / "coding/test-verification-policy/SKILL.md").read_text()
    go = (SKILLS / "languages/go/go-recipe-code-test-loop/SKILL.md").read_text()
    typescript = (SKILLS / "languages/typescript/typescript-code-test-loop/SKILL.md").read_text()
    vue = (SKILLS / "frontend-vue/vue-coding-conventions/SKILL.md").read_text()

    assert "Go writes the failing test first" in generic or "Go" in generic
    assert "test first" in go.lower()
    assert "vue-tsc" in vue
    assert "Vitest" in typescript


def test_code_test_workflows_handoff_generic_prerequisite_before_implementation() -> None:
    workflow_paths = (
        SKILLS / "orchestration/workflows/code-test-review.md",
        SKILLS / "orchestration/workflows/gitlab-code-test-review.md",
    )
    for path in workflow_paths:
        text = path.read_text()
        step_one_marker = (
            "### Step 1 — Code + Test Loop"
            if "### Step 1 — Code + Test Loop" in text
            else "## Step 1 — Code + Test Loop"
        )
        assert text.index("skills/coding/coding-rules/SKILL.md") < text.index(step_one_marker)
        assert "project context →" in text
        assert "applicable language root" in text
        assert "specific-to-specific conflicts" in text

    wrapper = (SKILLS / "design-and-analysis/code-test-review/SKILL.md").read_text()
    assert "skills/coding/coding-rules/SKILL.md" in wrapper
    assert "applicable language root" in wrapper

    for path in (
        SKILLS / "design-and-analysis/implement-feature-request/SKILL.md",
        SKILLS / "orchestration/orchestrator/SKILL.md",
    ):
        assert "skills/coding/coding-rules/SKILL.md" in path.read_text()
