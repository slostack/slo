"""Refresh committed skill files from the awesome-agi code-prompt library.

This is a dev-time helper only. It rebuilds ``skills/<group>/<slug>/SKILL.md``
using a consistent Slo wrapper around the source prompt content, adds grouped metadata
(frontmatter ``name`` / ``description`` / ``when_to_use`` / ``group`` /
``kind``), injects workflow-friendly examples, and sanitizes workstation-local
paths into Slo-friendly placeholders.

The runtime still reads only the committed ``skills/INDEX.md`` plus individual
``SKILL.md`` files via the ``read`` tool. This script exists so the committed
copy can stay aligned with the upstream prompt library without hand-editing
large numbers of markdown files.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Optional

import yaml

PROMPTS_ENV_VAR = "SLO_CODE_PROMPTS_DIR"
FEATURE_REQUESTS_ROOT = "${SLO_FEATURE_REQUESTS_DIR:-~/.slo/projects/<project_name>/feature-requests}"
FEATURE_SPECIFICATIONS_ROOT = (
    "${SLO_FEATURE_SPECIFICATIONS_DIR:-~/.slo/projects/<project_name>/feature-specifications}"
)

FRONTMATTER_RE = re.compile(r"\A[ \t]*---\s*\n(?P<body>.*?)\n[ \t]*---\s*\n", re.DOTALL)
FIRST_HEADING_RE = re.compile(r"\A#\s+(?P<title>.+?)\n+(?P<body>.*)\Z", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")

WORKFLOW_SLUGS: set[str] = {
    "orchestrator",
    "implement-feature-request",
    "feature-specifications",
    "feature-specifications-pre-hook",
    "feature-specifications-post-hook",
    "feature-specification-verification",
    "gather-feature-context",
    "breakdown-feature-spec-to-tasks",
    "specification-development",
    "code-test-review",
    "06-generate-feature-requests",
    "08-generating-test-plans",
    "09-plan-to-code",
    "development-reviews",
    "update-documentation-after-code-changes",
    "update-knowledge-base",
    "distill-learnings",
    "review-feature-code",
    "code-test-loop",
}
ORIENTATION_SLUGS: set[str] = {
    "claude",
    "readme",
    "research",
    "cli-readme",
    "tui-readme",
}
ANALYSIS_SLUGS: set[str] = {
    "orchestrator",
    "implement-feature-request",
    "feature-specifications",
    "feature-specifications-pre-hook",
    "feature-specifications-post-hook",
    "feature-specification-verification",
    "gather-feature-context",
    "breakdown-feature-spec-to-tasks",
    "specification-development",
    "code-test-review",
    "workflows",
    "find-how-it-works",
    "describe-a-problem",
    "debug-by-isolation",
    "generate-agents-md",
    "generate-research-md",
    "review-feature-code",
    "is-the-feature-completed",
    "update-documentation-after-code-changes",
    "update-knowledge-base",
    "distill-learnings",
    "development-reviews",
    "ubiquitous-language",
    "orchestrator",
    "readme",
    "research",
    "claude",
}
ARTIFACT_PATH_SKILLS: set[str] = {
    "implement-feature-request",
    "feature-specifications",
    "feature-specifications-pre-hook",
    "feature-specifications-post-hook",
    "feature-specification-verification",
    "gather-feature-context",
    "breakdown-feature-spec-to-tasks",
    "06-generate-feature-requests",
    "08-generating-test-plans",
    "09-plan-to-code",
    "01-test-setup",
    "02-test-execution",
    "03-teardown-and-reporting",
    "04-scenario-conventions",
    "05-step-definitions-with-domain-helpers",
    "07-debugging-failing-tests",
}
WHEN_TO_USE_OVERRIDES: dict[str, str] = {
    "build-textual-tuis": "Use when building or refactoring a Textual UI under `src/tui/`, including screens, widgets, renderers, and interaction flows.",
    "build-typer-cli-apps": "Use when building or revising a user-facing Typer CLI under `src/cli/`, especially when it launches a TUI or delegates through `TyperDispatch`.",
    "find-how-it-works": "Use when you need to trace an unfamiliar feature end-to-end through the codebase before changing it.",
    "gather-feature-context": "Use before drafting a feature specification when you need a sign-off-ready bundle of business, architecture, code, and KB context.",
}


@dataclass(frozen=True)
class SkillSpec:
    """Committed-skill metadata used to generate one ``SKILL.md`` file."""

    slug: str
    source_rel: Optional[str]
    description: str
    when_to_use: str
    group: str
    kind: str = "skill"
    examples: tuple[str, ...] = field(default_factory=tuple)
    title: Optional[str] = None
    manual_body: Optional[str] = None


def _resolve_repo_root() -> Path:
    """Return the slo repository root from ``scripts/``."""
    return Path(__file__).resolve().parent.parent


def _resolve_prompts_root() -> Path:
    """Resolve the upstream code-prompt directory used to refresh skills.

    Resolution order:
    1. ``$SLO_CODE_PROMPTS_DIR`` if set.
    2. ``~/Code/TS/awesome-agi/claude-md/code-prompts`` if it exists.

    Returns:
        Absolute prompt-library path.

    Raises:
        SystemExit: When no candidate path exists.
    """
    override = os.environ.get(PROMPTS_ENV_VAR)
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_dir():
            return path
        raise SystemExit(f"{PROMPTS_ENV_VAR} points to a missing directory: {path}")

    fallback = Path.home() / "Code" / "TS" / "awesome-agi" / "claude-md" / "code-prompts"
    if fallback.is_dir():
        return fallback.resolve()

    raise SystemExit(
        "Could not resolve the awesome-agi code-prompts directory. "
        f"Set {PROMPTS_ENV_VAR}=<path/to/code-prompts>."
    )


def _load_existing_skill_metadata(*, skills_dir: Path) -> dict[str, dict[str, str]]:
    """Load the committed skill metadata so descriptions survive refreshes.

    Args:
        skills_dir: Repo-local ``skills/`` directory.

    Returns:
        Mapping keyed by skill slug.
    """
    metadata: dict[str, dict[str, str]] = {}
    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(text=text)
        if frontmatter is None:
            continue
        data = yaml.safe_load(frontmatter) or {}
        if not isinstance(data, dict):
            continue
        slug = skill_file.parent.name
        description = _normalize_space(text=str(data.get("description", "")))
        when_to_use = _normalize_space(text=str(data.get("when_to_use", "")))
        if not when_to_use and description:
            description, when_to_use = _split_description(description=description)
        metadata[slug] = {
            "description": description,
            "when_to_use": when_to_use,
        }
    return metadata


def _extract_frontmatter(*, text: str) -> Optional[str]:
    """Return the YAML frontmatter body from ``text`` when present."""
    match = FRONTMATTER_RE.search(text)
    if match is None:
        return None
    return dedent(match.group("body")).strip()


def _split_description(*, description: str) -> tuple[str, str]:
    """Split a legacy combined description into summary + routing hint."""
    marker = " Use "
    if marker in description:
        head, tail = description.split(marker, 1)
        return head.strip(), f"Use {tail.strip()}"
    marker = " Read "
    if marker in description:
        head, tail = description.split(marker, 1)
        return head.strip(), f"Read {tail.strip()}"
    marker = " Apply "
    if marker in description:
        head, tail = description.split(marker, 1)
        return head.strip(), f"Apply {tail.strip()}"
    normalized = description.strip()
    return normalized, f"Use when you need guidance for: {normalized}"


def _normalize_space(*, text: str) -> str:
    """Collapse repeated whitespace into single spaces."""
    return " ".join(text.split())


def _guess_source_rel(*, slug: str, prompts_root: Path) -> Optional[str]:
    """Map an existing skill slug onto its source prompt path when possible."""
    if slug == "workflows":
        overview_path = prompts_root / "workflows" / "overview.md"
        if overview_path.is_file():
            return overview_path.relative_to(prompts_root).as_posix()

    candidates = [
        prompts_root / f"{slug}.md",
        prompts_root / "analyze" / f"{slug}.md",
        prompts_root / "integration-tests" / f"{slug}.md",
        prompts_root / "cli" / f"{slug}.md",
        prompts_root / "tui" / f"{slug}.md",
        prompts_root / "workflows" / f"{slug}.md",
        prompts_root / "vue-prompts" / f"{slug}.md",
        prompts_root / "vue-prompts" / "tutorial" / f"{slug}.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.relative_to(prompts_root).as_posix()
    return None


def _group_for(*, slug: str, source_rel: Optional[str]) -> str:
    """Assign a logical group used by the grouped runtime index."""
    if slug in ORIENTATION_SLUGS:
        return "orientation"
    if slug in ANALYSIS_SLUGS:
        return "design-and-analysis"
    if source_rel is None:
        return "design-and-analysis"

    first_part = Path(source_rel).parts[0]
    if first_part == "analyze":
        return "design-and-analysis"
    if first_part == "integration-tests":
        return "integration-tests"
    if first_part == "workflows":
        return "design-and-analysis"
    if first_part == "cli":
        return "cli"
    if first_part == "tui":
        return "tui"
    if first_part == "vue-prompts":
        return "frontend-vue"
    return "coding"


def _kind_for(*, slug: str) -> str:
    """Return whether ``slug`` is rendered as a workflow or an individual skill."""
    if slug in WORKFLOW_SLUGS:
        return "workflow"
    return "skill"


def _skill_repo_relpath(*, spec: SkillSpec) -> Path:
    """Return the repo-relative path for a committed skill file."""
    return Path("skills") / spec.group / spec.slug / "SKILL.md"


def _extra_specs() -> dict[str, SkillSpec]:
    """Return manually-defined skills that do not already exist in ``skills/``."""
    return {
        "claude": SkillSpec(
            slug="claude",
            source_rel="CLAUDE.md",
            description="Root entry-point guidance for the prompt library.",
            when_to_use="Read when you need the first-orientation rule that tells an agent which deeper prompt to open next.",
            group="orientation",
            examples=(
                'The user asks: "What should the agent read first when it enters this repo?"',
                "You are defining the repo-entry instructions and need the minimal CLAUDE.md contract.",
            ),
            title="CLAUDE.md Entry Point",
        ),
        "readme": SkillSpec(
            slug="readme",
            source_rel="README.md",
            description="Overview of the code-prompt library, its families, and the documentation triad.",
            when_to_use="Read when you need to understand how the prompt library is organized or which prompt family applies.",
            group="orientation",
            examples=(
                'The user asks: "How is the prompt library structured?"',
                "You need a high-level map before drilling into a specific convention file.",
            ),
            title="Prompt Library README",
        ),
        "research": SkillSpec(
            slug="research",
            source_rel="RESEARCH.md",
            description="Codebase index for the prompt library itself.",
            when_to_use="Read when you need to navigate the prompt-library repository or understand how its files are arranged.",
            group="orientation",
            examples=(
                'The user asks: "Where in the prompt library do the analysis prompts live?"',
                "You need a file-by-file inventory of the prompt-library repo before making changes.",
            ),
            title="Prompt Library RESEARCH",
        ),
        "cli-readme": SkillSpec(
            slug="cli-readme",
            source_rel="cli/README.md",
            description="Orientation guide for the CLI prompt family.",
            when_to_use="Read before working on CLI prompts so you choose the right CLI convention set.",
            group="cli",
            examples=(
                "The task touches a Python CLI and you need to know whether it follows the Typer or operator-command tradition.",
                "You want the reading order for the CLI prompt family before implementing a command.",
            ),
            title="CLI Prompt Family README",
        ),
        "tui-readme": SkillSpec(
            slug="tui-readme",
            source_rel="tui/README.md",
            description="Orientation guide for the Textual TUI prompt family.",
            when_to_use="Read before working on Textual TUI prompts so you know the TUI-specific scope and cross-links.",
            group="tui",
            examples=(
                "The task touches a Textual screen and you need the TUI prompt-family overview first.",
                "You want the narrow entry point for TUI conventions before opening the detailed build guide.",
            ),
            title="TUI Prompt Family README",
        ),
        "generate-agents-md": SkillSpec(
            slug="generate-agents-md",
            source_rel="analyze/generate-agents-md.md",
            description="Regenerate the repository AGENTS.md file from the current codebase.",
            when_to_use="Use when AGENTS.md is stale, incomplete, or needs to reflect new conventions, components, or architecture.",
            group="design-and-analysis",
            examples=(
                'The user asks: "Regenerate AGENTS.md after the new CLI and TUI landed."',
                "You changed project conventions and need the root agent guide to match reality.",
            ),
            title="Generate AGENTS.md",
        ),
        "generate-research-md": SkillSpec(
            slug="generate-research-md",
            source_rel="analyze/generate-research-md.md",
            description="Regenerate the repository RESEARCH.md codebase index.",
            when_to_use="Use when RESEARCH.md is stale or after structural changes added, removed, or moved major components.",
            group="design-and-analysis",
            examples=(
                'The user asks: "Refresh RESEARCH.md after the skills refactor."',
                "You added new source directories and need the codebase index to reflect them.",
            ),
            title="Generate RESEARCH.md",
        ),
        "orchestrator": SkillSpec(
            slug="orchestrator",
            source_rel=None,
            description="Gateway workflow that decides which skill or workflow to load next for the current task.",
            when_to_use="Use at the start or end of a turn when you need to route the task into the right Slo workflow, category, or individual skill.",
            group="design-and-analysis",
            kind="workflow",
            examples=(
                'The user asks: "Implement this feature request." Route into the feature-request workflow, then the matching build and test skills.',
                'The user asks: "Why is this integration test flaky?" Route into the integration-test anti-patterns and debugging workflow.',
            ),
            title="Orchestrator",
            manual_body=_orchestrator_body(),
        ),
        "implement-feature-request": SkillSpec(
            slug="implement-feature-request",
            source_rel=None,
            description="End-to-end workflow for turning a feature request or JIRA story into specs, code, tests, review, and documentation updates.",
            when_to_use="Use when the user asks for implementation of a feature request, JIRA story, or request.md artifact rather than a narrow one-off code change.",
            group="design-and-analysis",
            kind="workflow",
            examples=(
                'The user asks: "Implement /path/to/request.md." Use this workflow to gather context, draft or verify specs, implement, test, and document the result.',
                'The user asks: "Take this JIRA story from request to code." Use this workflow to break the work into spec, task, implementation, review, and docs phases.',
            ),
            title="Implement Feature Request",
            manual_body=_implement_feature_request_body(),
        ),
        "vscode-launch-configurations": SkillSpec(
            slug="vscode-launch-configurations",
            source_rel="vscode-launch-configurations.md",
            description="Reference guidance for VS Code launch configurations used by the workspace.",
            when_to_use="Read when you need to understand or review existing VS Code launch targets and debugger entry points.",
            group="coding",
            examples=(
                'The user asks: "What launch.json conventions does this workspace follow?"',
                "You need to inspect an existing debugger profile before adding a new one.",
            ),
            title="VS Code Launch Configurations",
        ),
        "build-vscode-launch-configurations": SkillSpec(
            slug="build-vscode-launch-configurations",
            source_rel="build-vscode-launch-configurations.md",
            description="Conventions for authoring or revising VS Code launch configurations.",
            when_to_use="Use when adding a new debugger target or refactoring launch.json entries for this workspace.",
            group="coding",
            examples=(
                'The user asks: "Add a VS Code debug target for the new worker."',
                "You need to rewrite launch.json so local run targets match the repo conventions.",
            ),
            title="Build VS Code Launch Configurations",
        ),
        "ubiquitous-language": SkillSpec(
            slug="ubiquitous-language",
            source_rel="ubiquitous-language.md",
            description="Cross-layer naming rule: one concept, one canonical name across CLI, services, DAOs, APIs, and frontend code.",
            when_to_use="Use when introducing, renaming, or reviewing domain terms that flow across more than one layer.",
            group="design-and-analysis",
            examples=(
                'The user asks: "Rename this concept across the API, DAO, and Vue store."',
                "You are reviewing a diff with several synonyms for the same concept and need the naming rule that breaks the tie.",
            ),
            title="Ubiquitous Language",
        ),
        "switch-environments-and-run-tests": SkillSpec(
            slug="switch-environments-and-run-tests",
            source_rel="switch-environments-and-run-tests.md",
            description="Environment-switching and test-execution conventions for the workspace.",
            when_to_use="Use when you need to move between local, test, or other env files and run the right test command safely.",
            group="coding",
            examples=(
                'The user asks: "Switch to the test environment and run the API test suite."',
                "You need the exact sequence for loading environment variables before pytest.",
            ),
            title="Switch Environments and Run Tests",
        ),
        "graph-gateway-invoke-convention": SkillSpec(
            slug="graph-gateway-invoke-convention",
            source_rel="graph-gateway-invoke-convention.md",
            description="Gateway invoke convention for graph entry points and orchestration seams.",
            when_to_use="Use when building or reviewing graph-adjacent gateway methods so their invoke contract stays consistent.",
            group="coding",
            examples=(
                'The user asks: "Add a new graph gateway entry point."',
                "You are reviewing a graph orchestration wrapper and need the invoke-contract rules.",
            ),
            title="Graph Gateway Invoke Convention",
        ),
        "derive-new-convention": SkillSpec(
            slug="derive-new-convention",
            source_rel="derive-new-convention.md",
            description="Process for deriving a new repeatable convention when no existing prompt covers the requested pattern.",
            when_to_use="Use when the task introduces a new architectural pattern that does not fit any existing skill cleanly.",
            group="design-and-analysis",
            examples=(
                "The user asks for a brand-new pattern that has no sibling prompt in the library.",
                "You need to formalize a new convention before implementing a feature that will recur.",
            ),
            title="Derive New Convention",
        ),
        "create-frontend-htmx-jinja2-fastapi-app": SkillSpec(
            slug="create-frontend-htmx-jinja2-fastapi-app",
            source_rel="create-frontend-htmx-jinja2-fastapi-app.md",
            description="Conventions for building server-rendered FastAPI + Jinja2 + HTMX frontends.",
            when_to_use="Use when creating or extending an HTMX/Jinja2 admin or operator surface backed by FastAPI.",
            group="coding",
            examples=(
                'The user asks: "Build a server-rendered admin screen with HTMX interactions."',
                "You need the canonical folder and template structure for a FastAPI + Jinja2 + HTMX app.",
            ),
            title="Create Frontend HTMX + Jinja2 + FastAPI App",
        ),
        "test-verification-policy-copy": SkillSpec(
            slug="test-verification-policy-copy",
            source_rel="test-verification-policy copy.md",
            description="Compatibility copy of the test-verification-policy guidance.",
            when_to_use="Use only when the user explicitly references the copy variant; otherwise prefer test-verification-policy.",
            group="coding",
            examples=(
                "The user explicitly asks for the `test-verification-policy copy` guidance.",
                "A legacy workflow names the copy variant and you need the matching artifact for compatibility.",
            ),
            title="Test Verification Policy Copy",
        ),
        **_git_ops_specs(),
    }


def _orchestrator_body() -> str:
    """Return the custom orchestrator workflow body."""
    return dedent(f"""
        ## Goal

        Route the current task into the **fewest high-signal skills** needed next.
        The orchestrator is the gateway workflow for the Slo skill library.

        ## Task Routing Order

        1. **Detect whether this is a workflow task or an individual-skill task.**
           - Workflow tasks span multiple phases: context gathering, spec writing,
             implementation, testing, review, or documentation updates.
           - Individual-skill tasks are narrower: write a router, update a client,
             fix a test, add a CLI command, build a Textual widget, and so on.
        2. **Check for feature artifacts first.**
           - If the request references a JIRA story, feature request, or `request.md`,
             route into `implement-feature-request` first.
           - Default storage roots:
             - Feature requests: `{FEATURE_REQUESTS_ROOT}`
             - Feature specifications: `{FEATURE_SPECIFICATIONS_ROOT}`
        3. **Choose the category.**
           - `design-and-analysis` for specs, tracing, debugging narratives, docs, KB, and review workflows.
           - `coding` for backend conventions and test conventions.
           - `git-ops` for syncing main, branching, committing, pushing, PR creation, PR review follow-up, and worktrees.
           - `cli` for Typer/operator-command work.
           - `tui` for Textual work.
           - `integration-tests` for cross-service scenarios and flaky-test debugging.
           - `frontend-vue` for Vue conventions and tutorials.
        4. **Load companion skills only when the main skill calls for them.**
           - Example: `feature-specifications` pairs with its PRE and POST hooks.
           - Example: integration-test authoring starts with `10-cardinal-rules-and-anti-patterns` before scenario-specific prompts.
        5. **Return only the next best skills.**
           Prefer a short ordered list over a long exhaustive catalog.

        ## Category Routing Hints

        ### Feature work

        - Implementation request for a feature or story → `implement-feature-request`
        - Need to draft a spec only → `feature-specifications-pre-hook`, `feature-specifications`, `feature-specifications-post-hook`
        - Need to break an approved spec into tasks → `breakdown-feature-spec-to-tasks`
        - Need to review shipped code against a spec → `review-feature-code`

        ### Backend / coding conventions

        - Routers → `build-routers`
        - Application services → `build-application-services`
        - Domain models/services → `build-domain-features`
        - Clients → `build-clients`
        - Middleware → `build-middleware`
        - Event handlers → `build-event-handlers`
        - Celery → `build-celery-workers`
        - DBOS workflow/schedulers → `build-dbos-workflow-orchestration-pattern`, `build-schedulers-tasks-with-dbos`
        - Agent tools / LangGraph → `build-agent-tools`, `build-react-agent-with-langgraph`, `graph-gateway-invoke-convention`
        - Tests → `code-test-loop`, `test-verification-policy`, plus the matching `test-*` skill

        ### Git operations

        - Need the umbrella git policy first → `branching-and-commit-conventions`
        - Need latest `main` before work starts → `sync-main`
        - Need a task branch from latest `main` → `create-feature-branch`
        - Need to save local work to git and push it → `commit-and-push`
        - Need PR title/body only → `generate-pr-description`
        - Need to open a PR → `create-pull-request` (after `generate-pr-description`)
        - Need current PR context before review/follow-up → `load-pr-context`
        - Need to address PR comments or conflicts → `fix-pr-review`
        - Need latest `main` or parallel work without disturbing the current tree → `worktrees`

        ### CLI / TUI

        - Product CLI under `src/cli/` → `cli-readme`, then `build-typer-cli-apps`
        - Operator/deployment CLI → `cli-readme`, then the relevant `build-cli-*` skills
        - Textual app/screens/widgets → `tui-readme`, then `build-textual-tuis`

        ### Integration tests

        - Any integration-test task starts with `10-cardinal-rules-and-anti-patterns`
        - New scenario stack/setup → `01-test-setup`
        - Scenario authoring → `02-test-execution`, `04-scenario-conventions`, `05-step-definitions-with-domain-helpers`
        - Feature request / plan → `06-generate-feature-requests`, `08-generating-test-plans`, `09-plan-to-code`
        - Failing test → `07-debugging-failing-tests`, optionally `11-integration-test-investigation-format`

        ### Documentation / knowledge capture

        - KB updates → `update-knowledge-base`
        - Repo docs / AGENTS / RESEARCH refresh → `update-documentation-after-code-changes`, `generate-agents-md`, `generate-research-md`
        - Session learnings → `distill-learnings`

        ## Output Format

        Return a short ordered list:

        ```text
        Relevant skills:
        1. <skill-name> — why it applies now
        2. <skill-name> — why it applies next
        ```

        If no skill applies, return `Relevant skills: none`.
        """).strip() + "\n"


def _implement_feature_request_body() -> str:
    """Return the custom end-to-end implementation workflow body."""
    return dedent(f"""
        ## Goal

        Deliver a feature request or JIRA story from planning artifact to tested
        implementation without skipping the intermediate workflow steps.

        ## Default Slo Artifact Layout

        Unless the user explicitly overrides these paths, use:

        ```text
        {FEATURE_REQUESTS_ROOT}
        └── <feature_slug>/
            └── request.md

        {FEATURE_SPECIFICATIONS_ROOT}
        └── <feature_slug>/
            ├── overview.md
            ├── 01.a-sub-step.md
            └── ...
        ```

        Honor `SLO_FEATURE_REQUESTS_DIR` and `SLO_FEATURE_SPECIFICATIONS_DIR` when
        they are present. Otherwise, derive the roots above under the active
        `<project_name>`.

        ## Workflow

        1. **Load context first.**
           - Read the relevant request artifact, story, or `request.md`.
           - Read project guardrails (`CLAUDE.md`, `AGENTS.md`, `RESEARCH.md`).
           - Read the Knowledge Base before inferring architecture or domain rules.
        2. **Produce or validate the implementation spec.**
           - Use `feature-specifications-pre-hook`.
           - Use `feature-specifications`.
           - Use `feature-specifications-post-hook`.
           - If a draft spec already exists, run `feature-specification-verification` instead of rewriting blindly.
        3. **Break the spec into executable tasks.**
           - Use `breakdown-feature-spec-to-tasks`.
           - Sequence tasks so each can be implemented and tested independently.
        4. **Choose the implementation skills.**
           - Match the task shape to the right build/test skills (`build-routers`,
             `build-domain-features`, `build-application-services`, `build-clients`,
             `build-agent-tools`, CLI/TUI prompts, etc.).
        5. **Work in the code+test loop.**
           - Apply `code-test-loop` and the matching `test-*` prompts.
           - Land one small unit, run its tests, then continue.
        6. **Run a structured review pass.**
           - Use `review-feature-code` before declaring the work done.
           - Use `development-reviews` when the review-agent handshake applies.
        7. **Update documentation and knowledge capture.**
           - Use `update-documentation-after-code-changes`.
           - Use `update-knowledge-base`.
           - Use `distill-learnings` when you discovered something subtle.

        ## Non-Negotiables

        - Do not jump straight from a request into coding when a spec is missing or stale.
        - Do not invent storage paths for requests/specifications; use the Slo roots above.
        - Do not skip the code+test loop.
        - Do not close the task without documentation and KB updates when the work changed conventions or surfaced new gotchas.

        ## Output Expectation

        When following this workflow, keep the user informed of the current phase:

        - Context gathered
        - Spec drafted or verified
        - Tasks broken down
        - Implementation in progress
        - Tests passing
        - Docs / KB updated
        """).strip() + "\n"


def _git_ops_specs() -> dict[str, SkillSpec]:
    """Return the manually-authored git workflow skills."""
    return {
        "git-ops-orchestrator": SkillSpec(
            slug="git-ops-orchestrator",
            source_rel=None,
            description="Gateway workflow for routing a git request into the right branching, commit, PR, or worktree skill.",
            when_to_use="Use when the user asks for git help and you need to decide whether the next step is syncing main, branching, committing, opening a PR, loading PR context, fixing review feedback, or using a worktree.",
            group="git-ops",
            kind="workflow",
            examples=(
                'The user asks: "Help me get this branch ready for a PR." Route into the smallest relevant git-ops workflow.',
                'The user asks: "I need the latest main without disturbing my current changes." Route into the worktree flow.',
            ),
            title="Git Ops Orchestrator",
            manual_body=_git_ops_orchestrator_body(),
        ),
        "branching-and-commit-conventions": SkillSpec(
            slug="branching-and-commit-conventions",
            source_rel="branching-and-commit-conventions.md",
            description="Repo-aware git safety rails, branch naming rules, commit message defaults, and PR guardrails distilled into one operating policy.",
            when_to_use="Use before creating a branch, commit, or PR when you need the git rules that all of the other git-ops skills assume.",
            group="git-ops",
            examples=(
                'The user asks: "What git conventions should I follow in this repo?"',
                "You are about to branch or commit and want the policy before touching git.",
            ),
            title="Branching and Commit Conventions",
            manual_body=_branching_and_commit_conventions_body(),
        ),
        "sync-main": SkillSpec(
            slug="sync-main",
            source_rel=None,
            description="Refresh local main from remote safely, without clobbering in-flight work.",
            when_to_use="Use before starting a new task or whenever the user asks to pull the latest main branch.",
            group="git-ops",
            examples=(
                'The user asks: "Pull the latest main before we start."',
                "You want a fresh branch base and need to make sure local `main` matches origin first.",
            ),
            title="Sync Main",
            manual_body=_sync_main_body(),
        ),
        "create-feature-branch": SkillSpec(
            slug="create-feature-branch",
            source_rel=None,
            description="Create a task-scoped feature branch from the latest main using repo conventions or safe Slo defaults.",
            when_to_use="Use when new implementation or debugging work needs its own branch rather than happening on main.",
            group="git-ops",
            examples=(
                'The user asks: "Create a branch for AGI-1234 before we code."',
                "You finished planning and need a clean task branch from updated `main`.",
            ),
            title="Create Feature Branch",
            manual_body=_create_feature_branch_body(),
        ),
        "commit-and-push": SkillSpec(
            slug="commit-and-push",
            source_rel=None,
            description="Stage the intended files, confirm a repo-appropriate commit message, commit safely, and push to the correct upstream branch.",
            when_to_use="Use when the user explicitly wants local work saved to git or pushed to the remote branch.",
            group="git-ops",
            kind="workflow",
            examples=(
                'The user asks: "Commit these changes and push the branch."',
                "You have a reviewed diff and need the safe stage → commit → push sequence.",
            ),
            title="Commit and Push",
            manual_body=_commit_and_push_body(),
        ),
        "generate-pr-description": SkillSpec(
            slug="generate-pr-description",
            source_rel=None,
            description="Generate a PR title and body from the branch, commits, diff, and repository PR template.",
            when_to_use="Use when the user wants PR-ready text before opening the pull request.",
            group="git-ops",
            examples=(
                'The user asks: "Draft the PR description for this branch."',
                "You need a template-aware PR body instead of writing one from scratch.",
            ),
            title="Generate PR Description",
            manual_body=_generate_pr_description_body(),
        ),
        "create-pull-request": SkillSpec(
            slug="create-pull-request",
            source_rel=None,
            description="Open a pull request against the correct base branch using a generated, template-aware title and body.",
            when_to_use="Use after the branch is pushed and the user wants a pull request created or prepared.",
            group="git-ops",
            kind="workflow",
            examples=(
                'The user asks: "Open a PR for this branch."',
                "You already pushed the branch and now need the exact PR-creation flow.",
            ),
            title="Create Pull Request",
            manual_body=_create_pull_request_body(),
        ),
        "load-pr-context": SkillSpec(
            slug="load-pr-context",
            source_rel=None,
            description="Collect the current PR's metadata, diff themes, review comments, and next actions into one brief.",
            when_to_use="Use when the user asks about the current PR, wants review context, or needs to follow up on feedback.",
            group="git-ops",
            examples=(
                'The user asks: "What is going on in this PR?"',
                "You need the PR summary and comment context before responding to review.",
            ),
            title="Load PR Context",
            manual_body=_load_pr_context_body(),
        ),
        "fix-pr-review": SkillSpec(
            slug="fix-pr-review",
            source_rel=None,
            description="Address PR review comments, integrate the latest base branch safely, rerun verification, and push the follow-up.",
            when_to_use="Use when the user asks to fix PR comments, resolve conflicts, or make the branch mergeable after review.",
            group="git-ops",
            kind="workflow",
            examples=(
                'The user asks: "Fix the PR review comments and push the updates."',
                "A PR is blocked on feedback or base-branch conflicts and needs a clean follow-up pass.",
            ),
            title="Fix PR Review",
            manual_body=_fix_pr_review_body(),
        ),
        "worktrees": SkillSpec(
            slug="worktrees",
            source_rel=None,
            description="Use git worktrees for latest-main reads, parallel branches, and reviewer/writer isolation without disturbing the current checkout.",
            when_to_use="Use when you need clean main context or parallel branch work while preserving the user's current working tree.",
            group="git-ops",
            examples=(
                'The user asks: "Inspect origin/main without touching my current branch."',
                "You want a separate clean checkout for a reviewer session or an alternate implementation path.",
            ),
            title="Worktrees",
            manual_body=_worktrees_body(),
        ),
    }


def _git_ops_orchestrator_body() -> str:
    """Return the git-ops routing workflow body."""
    return dedent("""
        ## Goal

        Route a git-related request into the **smallest safe git workflow** needed next.
        Use this skill to avoid mixing branch creation, commit policy, PR generation,
        and review follow-up into one fuzzy instruction.

        ## Routing Order

        1. **Need the policy first?**
           - Load `branching-and-commit-conventions` when the user is asking what rules apply,
             or when later git steps would otherwise guess.
        2. **Need the latest base branch?**
           - Load `sync-main` when the user asks to pull the latest `main`.
           - Load `worktrees` instead when the current checkout must remain untouched.
        3. **Need a new branch for new work?**
           - Load `create-feature-branch` after `sync-main`.
        4. **Need to save local work?**
           - Load `commit-and-push`.
        5. **Need a PR?**
           - Load `generate-pr-description` first, then `create-pull-request`.
        6. **Need to understand or fix an existing PR?**
           - Load `load-pr-context` to read the PR.
           - Load `fix-pr-review` when the task is to address review comments or conflicts.

        ## Output Format

        Return a short ordered list:

        ```text
        Relevant git-ops skills:
        1. <skill-name> — why it applies now
        2. <skill-name> — why it applies next
        ```

        If none apply, return `Relevant git-ops skills: none`.
        """).strip() + "\n"


def _branching_and_commit_conventions_body() -> str:
    """Return the umbrella git policy body."""
    return dedent("""
        ## Goal

        Resolve repo-specific git conventions into one safe operating policy before
        branching, committing, pushing, or opening a PR.

        ## Precedence

        1. **Repo-local instructions win.** Read `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`,
           or other repo docs first when they define git rules.
        2. **User instructions override defaults** when explicit.
        3. **Slo defaults below apply only when the repo is silent or inconsistent.**

        ## Non-Negotiable Safety Rules

        - Never commit directly on `main`.
        - Never commit unless the user asked for a commit.
        - Never amend a published commit unless the user explicitly asks.
        - Never force-push `main` or `master`.
        - Stage specific files only; do not default to `git add .` or `git add -A`.
        - Check `git status --short --branch` before any branch / commit / push action.
        - Prefer `worktrees` when you need clean `main` context without touching the current tree.

        ## Slo Default Branch Naming

        Use the repo's own convention when it exists. Otherwise default to:

        - With ticket ID: `<TICKET-ID>-<short-kebab-description>`
        - Without ticket ID: `feature-<short-kebab-description>`

        Examples:

        - `AGI-1234-fix-pr-template-routing`
        - `feature-refresh-skills-index`

        If the repo already standardizes on lowercase ticket-only names or typed prefixes,
        preserve that repo convention instead of rewriting it.

        ## Slo Default Commit Messages

        Use the repo's own commit format when documented. Otherwise default to:

        - First substantial commit on a ticket branch: `<TICKET-ID>: <imperative summary>`
        - No ticket: `<type>: <imperative summary>` where type is one of `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
        - Follow-up commits may use the short typed form (`fix: ...`, `test: ...`)

        Keep the subject line short and specific. Add a body only when the repo or the
        user wants more detail.

        ## Push and PR Defaults

        - First push: `git push -u origin HEAD`
        - Later pushes: `git push`
        - Default PR base: `main`
        - Do not force-push review follow-ups unless the user explicitly requests that strategy.

        ## Companion Skills

        - `sync-main` — refresh local `main`
        - `create-feature-branch` — cut a task branch from updated `main`
        - `commit-and-push` — safe stage → commit → push flow
        - `generate-pr-description` and `create-pull-request` — PR preparation and creation
        - `load-pr-context` and `fix-pr-review` — review follow-up flows
        - `worktrees` — non-disruptive latest-main or parallel-branch work
        """).strip() + "\n"


def _sync_main_body() -> str:
    """Return the main-sync workflow body."""
    return dedent("""
        ## Goal

        Refresh local `main` from remote **without clobbering uncommitted work**.

        ## Workflow

        1. Inspect the current state first:
           ```bash
           git status --short --branch
           ```
        2. If the current checkout is dirty and the user only needs the latest `main`
           for reading, comparison, or context gathering, stop and use `worktrees` instead.
        3. If the user explicitly wants in-place `main` updated while the current checkout
           is dirty, ask before stashing, checking out, or moving branches.
        4. When it is safe to update local `main`:
           ```bash
           git fetch origin
           git checkout main
           git pull origin main
           ```
        5. If the repo uses a different default branch, detect it first and substitute it
           consistently instead of assuming `main`.
        6. Report the resulting branch and whether it is up to date with origin.

        ## Non-Negotiables

        - Never discard or stash user changes without confirmation.
        - Never pretend a dirty checkout is safe just because `git pull` would fail loudly.
        - Prefer `worktrees` over branch-hopping when the task is read-only or comparative.
        """).strip() + "\n"


def _create_feature_branch_body() -> str:
    """Return the feature-branch creation workflow body."""
    return dedent("""
        ## Goal

        Create a clean task branch from the latest base branch using repo conventions or
        the Slo defaults from `branching-and-commit-conventions`.

        ## Workflow

        1. Ensure the base branch is fresh.
           - If local `main` is stale, run `sync-main` first.
           - If the current working tree must remain untouched, use `worktrees` instead.
        2. Inspect the current checkout:
           ```bash
           git status --short --branch
           ```
        3. If there are uncommitted changes on `main`, do not branch blindly. Ask whether
           the branch should be created from dirty `HEAD` or from a clean updated base.
        4. Derive the branch name.
           - Repo-local naming convention wins.
           - Otherwise default to `<TICKET-ID>-<short-kebab-description>`.
           - If there is no ticket, use `feature-<short-kebab-description>`.
        5. When the base and branch name are clear:
           ```bash
           git checkout -b <branch-name>
           ```
        6. Confirm the new current branch with:
           ```bash
           git rev-parse --abbrev-ref HEAD
           ```

        ## Non-Negotiables

        - Never start implementation work directly on `main`.
        - One branch should correspond to one focused task or feature slice.
        - If the task is exploratory or parallel to existing work, prefer `worktrees` over repeatedly switching branches.
        """).strip() + "\n"


def _commit_and_push_body() -> str:
    """Return the commit-and-push workflow body."""
    return dedent("""
        ## Goal

        Save the intended work to git, with explicit staging, a confirmed commit message,
        and the correct push behavior for first vs subsequent pushes.

        ## Workflow

        1. Verify the branch and status:
           ```bash
           git status --short --branch
           git rev-parse --abbrev-ref HEAD
           ```
        2. If the branch is `main`, stop. Route into `create-feature-branch` first.
        3. Run the repo's formatter and the right tests for the changed surface when the
           task requires validation. If you skip verification, say so explicitly.
        4. Stage only the intended files:
           ```bash
           git add <specific-file-1> <specific-file-2>
           ```
        5. Derive the commit message using `branching-and-commit-conventions`.
        6. Show the proposed message to the user and wait for confirmation before committing.
        7. Commit:
           ```bash
           git commit -m "<confirmed message>"
           ```
        8. Decide whether this is the first push for the branch.
           - No upstream yet:
             ```bash
             git push -u origin HEAD
             ```
           - Upstream already exists:
             ```bash
             git push
             ```
        9. If this was the first push and the user wants a PR, route into
           `generate-pr-description` and then `create-pull-request`.

        ## Non-Negotiables

        - Never commit unless the user asked for a commit.
        - Never default to `git add .` or `git add -A`.
        - Never amend or force-push a published commit unless the user explicitly asks.
        - Always make the commit message visible to the user before creating the commit.
        """).strip() + "\n"


def _generate_pr_description_body() -> str:
    """Return the PR-description workflow body."""
    return dedent("""
        ## Goal

        Produce a PR title and body that actually match the branch, diff, and repository
        template instead of improvising a vague summary.

        ## Workflow

        1. Gather git context:
           ```bash
           git rev-parse --abbrev-ref HEAD
           git log --oneline main..HEAD
           git diff main...HEAD --stat
           ```
        2. Load the repository PR template if it exists.
           - Start with `.github/PULL_REQUEST_TEMPLATE.md`.
           - If there are multiple templates, choose the one closest to the changed area.
        3. Derive the PR title.
           - Prefer the repo's own title convention.
           - Otherwise use the ticket ID plus an imperative summary when one is available.
        4. Fill every template section with real content from the diff.
           - Explain **why** the change exists.
           - Summarize **what** changed.
           - Record **how it was verified**.
           - Call out **risks / rollout concerns** honestly.
        5. If no template exists, output a concise fallback body with sections for Summary,
           Verification, and Risks.
        6. Return the title and full body ready for `create-pull-request`.

        ## Non-Negotiables

        - Do not leave placeholder text unfilled.
        - Do not dump a raw diff as the PR description.
        - If the repo has a PR template, use it instead of inventing your own structure.
        """).strip() + "\n"


def _create_pull_request_body() -> str:
    """Return the PR-creation workflow body."""
    return dedent("""
        ## Goal

        Open a pull request against the right base branch with a title and body that were
        prepared deliberately rather than improvised at the last second.

        ## Workflow

        1. Verify the branch is pushed and is not `main`.
        2. Generate the title and body first with `generate-pr-description`.
        3. Confirm the base branch.
           - Default to `main` unless the repo or the user says otherwise.
        4. If GitHub CLI authentication is missing, stop and tell the user to run:
           ```bash
           gh auth login
           ```
        5. Create the PR:
           ```bash
           gh pr create --title "<title>" --body "<body>" --base main
           ```
        6. Return the PR URL.
        7. If the repo uses PR notifications or follow-up threads, mention that next step to the user.

        ## Non-Negotiables

        - Never open a PR from `main`.
        - Never skip the title/body generation step when a repo template exists.
        - Do not auto-merge or delete branches unless the user explicitly asks.
        """).strip() + "\n"


def _load_pr_context_body() -> str:
    """Return the PR-context loading workflow body."""
    return dedent("""
        ## Goal

        Build one reliable brief for the current pull request so review, debugging, and
        follow-up work start from facts instead of scattered CLI output.

        ## Workflow

        1. Identify the PR.
           - Prefer an explicit PR URL or number from the user.
           - Otherwise derive it from the current branch.
        2. Gather the PR metadata:
           ```bash
           gh pr view <number> --json number,title,body,baseRefName,headRefName,url,reviewDecision
           ```
        3. Gather the change shape:
           ```bash
           git log --oneline <base>..HEAD
           git diff <base>...HEAD --stat
           ```
        4. Gather review comments and discussion threads.
        5. If the title or branch includes a ticket ID, note it and load any linked issue context the repo workflow expects.
        6. Summarize the PR in a structured brief:
           - identity
           - intent
           - changed surfaces
           - open review feedback
           - risks
           - next recommended actions

        ## Non-Negotiables

        - Do not assume a PR exists for the current branch; verify it.
        - Prefer local branch + PR metadata together, not one without the other.
        - If multiple PRs could match, ask instead of guessing.
        """).strip() + "\n"


def _fix_pr_review_body() -> str:
    """Return the PR-review fix workflow body."""
    return dedent("""
        ## Goal

        Address PR feedback cleanly: understand the review state, integrate the latest
        base branch safely, fix the requested issues, verify the result, and push the
        follow-up without making git history worse.

        ## Workflow

        1. Load `load-pr-context` first so the current review state is explicit.
        2. Classify comments into:
           - required fix
           - suggested improvement
           - question / clarification
        3. Refresh the branch against the latest base branch.
           - Follow repo instructions if they specify merge vs rebase.
           - If the repo is silent, prefer merging the updated base branch instead of force-push-heavy rebasing.
        4. Fix the applicable comments and resolve conflicts.
        5. Run the relevant formatter and tests for the changed area.
        6. Stage specific files only, propose a follow-up commit message, commit, and push.
        7. Report what was fixed, what was intentionally skipped, and what still needs a human decision.

        ## Non-Negotiables

        - Do not silently ignore comments.
        - Do not force-push by default.
        - Do not claim a PR is mergeable without rerunning the relevant verification.
        """).strip() + "\n"


def _worktrees_body() -> str:
    """Return the worktree guidance body."""
    return dedent("""
        ## Goal

        Use git worktrees to inspect `origin/main` or work on parallel branches without
        disturbing the user's current checkout.

        ## Preferred Use Cases

        - Read the latest `main` while the current branch is dirty.
        - Spin up a reviewer checkout alongside a writer checkout.
        - Compare two implementation approaches in parallel.
        - Prepare a clean branch from `origin/main` without branch-hopping.

        ## Workflow

        1. Fetch the latest remote state:
           ```bash
           git fetch origin main
           ```
        2. Add a read-only-style main worktree when you only need clean context:
           ```bash
           git worktree add ../.worktrees/<repo>-main origin/main
           ```
        3. Add a new branch worktree when you need to make changes in parallel:
           ```bash
           git worktree add -b <branch-name> ../.worktrees/<repo>-<purpose> origin/main
           ```
        4. Do the investigation or implementation in the new path.
        5. Remove the worktree when finished:
           ```bash
           git worktree remove ../.worktrees/<repo>-<purpose>
           ```
        6. If worktrees are impossible in the current environment, only then fall back to
           stash → checkout → restore, and record the original branch / status first.

        ## Non-Negotiables

        - Do not disturb the user's current working tree when a worktree will do.
        - Clean up temporary worktrees when the task is complete.
        - If you fall back to stash/checkout, restore the original state exactly.
        """).strip() + "\n"


def _build_skill_specs(*, prompts_root: Path, skills_dir: Path) -> dict[str, SkillSpec]:
    """Build the full generation manifest for committed skills.

    Args:
        prompts_root: Upstream prompt-library root.
        skills_dir: Repo-local ``skills/`` directory.

    Returns:
        Mapping keyed by skill slug.
    """
    metadata = _load_existing_skill_metadata(skills_dir=skills_dir)
    specs: dict[str, SkillSpec] = {}

    existing_slugs = sorted({path.parent.name for path in skills_dir.rglob("SKILL.md")})
    for slug in existing_slugs:
        description = metadata.get(slug, {}).get("description", "")
        when_to_use = metadata.get(slug, {}).get("when_to_use", "")
        source_rel = _guess_source_rel(slug=slug, prompts_root=prompts_root)
        if not description or source_rel is None:
            continue
        resolved_when_to_use = WHEN_TO_USE_OVERRIDES.get(slug, when_to_use or description)
        specs[slug] = SkillSpec(
            slug=slug,
            source_rel=source_rel,
            description=description,
            when_to_use=resolved_when_to_use,
            group=_group_for(slug=slug, source_rel=source_rel),
            kind=_kind_for(slug=slug),
        )

    specs.update(_extra_specs())
    return dict(sorted(specs.items()))


def _read_source_body(*, spec: SkillSpec, prompts_root: Path) -> str:
    """Return the source markdown body used for ``spec``.

    Args:
        spec: Skill generation spec.
        prompts_root: Upstream prompt-library root.

    Returns:
        Raw markdown body.
    """
    if spec.manual_body is not None:
        return spec.manual_body
    if spec.source_rel is None:
        return ""
    source_path = prompts_root / spec.source_rel
    return source_path.read_text(encoding="utf-8")


def _derive_title(*, spec: SkillSpec, raw_body: str) -> str:
    """Pick the rendered H1 title for a skill file."""
    if spec.title:
        return spec.title
    match = FIRST_HEADING_RE.search(raw_body.strip())
    if match is not None:
        return match.group("title").strip()
    return spec.slug.replace("-", " ").title()


def _strip_first_heading(*, raw_body: str) -> str:
    """Remove the source file's leading H1 so Slo can supply its own wrapper."""
    stripped = raw_body.strip()
    match = FIRST_HEADING_RE.search(stripped)
    if match is None:
        return stripped + "\n"
    return match.group("body").lstrip() + "\n"


def _build_examples(*, spec: SkillSpec) -> tuple[str, ...]:
    """Return user-facing example prompts for a skill."""
    if spec.examples:
        return spec.examples

    topic = spec.slug.replace("-", " ")
    if spec.slug.startswith("build-"):
        return (
            f'The user asks: "Add or revise the {topic[6:]} for this feature."',
            f"You want the canonical build pattern before touching {topic[6:]}.",
        )
    if spec.slug.startswith("test-"):
        return (
            f'The user asks: "Write or revise the tests covered by {topic}."',
            "You finished coding and need the matching test convention before calling the work done.",
        )
    if spec.slug.startswith("setup-"):
        return (
            f'The user asks: "Set up {topic[6:]} for this project."',
            "You are bootstrapping project infrastructure and need the setup checklist first.",
        )
    if spec.slug.startswith("update-"):
        return (
            f'The user asks: "Update {topic[7:]} after this change."',
            "You are at the close-out phase and need the right post-change documentation workflow.",
        )
    if spec.slug.startswith("generate-"):
        return (
            f'The user asks: "Generate {topic[9:]} for this repository."',
            "You need a deterministic generation workflow for an existing project artifact.",
        )
    if spec.kind == "workflow":
        return (
            f"The user asks for an end-to-end workflow that fits: {spec.description}",
            spec.when_to_use,
        )
    return (
        f"The user asks for help with: {spec.description}",
        spec.when_to_use,
    )


def _build_artifact_paths_block() -> str:
    """Return the standard Slo artifact-path block for planning-related skills."""
    return dedent(f"""
        ## Slo defaults for request and specification artifacts

        Unless the user explicitly overrides these paths, use:

        ```text
        <feature-requests-root> = {FEATURE_REQUESTS_ROOT}
        <feature-specifications-root> = {FEATURE_SPECIFICATIONS_ROOT}
        ```

        Use one folder per feature:

        ```text
        <feature-requests-root>/
        └── 01-example-feature/
            └── request.md

        <feature-specifications-root>/
        └── 01-example-feature/
            ├── overview.md
            ├── 01.a-sub-step.md
            └── plan.md
        ```
        """).strip()


def _sanitize_body(
    *,
    body: str,
    spec: SkillSpec,
    prompts_root: Path,
    current_output_path: Path,
    source_to_output_relpath: dict[str, str],
) -> str:
    """Sanitize workstation-local references and prompt-library links.

    Args:
        body: Source markdown body without the leading H1.
        spec: Skill being rendered.
        prompts_root: Upstream prompt-library root.
        current_output_path: Repo-relative path of the skill being rendered.
        source_to_output_relpath: Source-prompt relative path -> committed skill path.

    Returns:
        Sanitized markdown body.
    """
    text = body.replace("\r\n", "\n")
    text = _rewrite_markdown_links(
        text=text,
        source_rel=spec.source_rel,
        prompts_root=prompts_root,
        current_output_path=current_output_path,
        source_to_output_relpath=source_to_output_relpath,
    )
    text = _replace_prompt_library_paths(
        text=text,
        prompts_root=prompts_root,
        source_to_output_relpath=source_to_output_relpath,
    )
    text = _replace_local_workspace_roots(text=text)
    text = _replace_feature_artifact_paths(text=text)
    text = _replace_project_memory_paths(text=text)
    text = text.replace("code-prompts/skills/", "skills/")
    text = text.replace("../prompts/skills/", "skills/")
    text = text.replace("prompts/skills/", "skills/")
    text = text.replace("skills/skills/", "skills/")
    text = text.replace(
        "../vue/vue-coding-conventions.md", "skills/frontend-vue/vue-coding-conventions/SKILL.md"
    )
    text = text.replace("`SLO_KB_DIR` environment variable", "`SLO_KB_DIR`")
    return text.rstrip() + "\n"


def _rewrite_markdown_links(
    *,
    text: str,
    source_rel: Optional[str],
    prompts_root: Path,
    current_output_path: Path,
    source_to_output_relpath: dict[str, str],
) -> str:
    """Rewrite prompt-library markdown links to committed-skill sibling links."""

    source_dir = Path(source_rel).parent if source_rel is not None else Path(".")

    def _replace(match: re.Match[str]) -> str:
        label = match.group("label")
        target = match.group("target").strip()
        if target.startswith(("http://", "https://")):
            return match.group(0)

        target_without_anchor = target.split("#", 1)[0]
        if target_without_anchor.startswith("file://"):
            candidate_path = Path(target_without_anchor.removeprefix("file://"))
        else:
            candidate_path = (prompts_root / source_dir / target_without_anchor).resolve()
            if not candidate_path.exists() and Path(target_without_anchor).is_absolute():
                candidate_path = Path(target_without_anchor)

        try:
            relative = candidate_path.relative_to(prompts_root).as_posix()
        except ValueError:
            if target_without_anchor.endswith(".md"):
                return f"`{label}`"
            return match.group(0)

        committed_target = source_to_output_relpath.get(relative)
        if committed_target is None:
            return f"`{label}`"
        relative_target = os.path.relpath(
            committed_target,
            start=current_output_path.parent.as_posix(),
        )
        return f"[{label}]({relative_target})"

    return MARKDOWN_LINK_RE.sub(_replace, text)


def _replace_prompt_library_paths(
    *,
    text: str,
    prompts_root: Path,
    source_to_output_relpath: dict[str, str],
) -> str:
    """Replace source-prompt paths with committed-skill paths."""
    output = text
    for source_rel, committed in sorted(
        source_to_output_relpath.items(), key=lambda item: len(item[0]), reverse=True
    ):
        absolute = str((prompts_root / source_rel).resolve())
        replacements = {
            f"file://{absolute}",
            absolute,
            source_rel,
            f"local_files/prompts/code_prompts/{source_rel}",
            f"prompts/rules/prompts/{source_rel}",
        }
        if source_rel.startswith("analyze/"):
            replacements.add(f"local_files/prompts/{source_rel}")
        for candidate in replacements:
            output = output.replace(candidate, committed)
    return output


def _replace_local_workspace_roots(*, text: str) -> str:
    """Replace workstation-local repo roots with portable placeholders."""
    output = text.replace("/Users/siddharth/Code/KnowledgeBase/KB", "$SLO_KB_DIR")
    output = output.replace("/Users/sidravic/Code/KnowledgeBase/KB", "$SLO_KB_DIR")
    output = output.replace("/Users/siddharth/Code/TS/LEARNINGS.md", "<workspace>/LEARNINGS.md")
    output = output.replace("/Users/sidravic/Code/PythonApps/sentinel", "<workspace>/sentinel")
    output = output.replace("/Users/sidravic/Code/PythonApps", "<workspace>")
    output = re.sub(
        pattern=r"/Users/[^/\s]+/Code/(?:TS|Pi|PythonApps)/([A-Za-z0-9_.-]+)",
        repl=r"<workspace>/\1",
        string=output,
    )
    output = output.replace("file://<workspace>/", "<workspace>/")
    output = output.replace("~/.claude/projects/", "<project-memory>/")
    return output


def _replace_feature_artifact_paths(*, text: str) -> str:
    """Replace ad-hoc feature-request/specification paths with Slo roots."""
    output = text
    output = re.sub(
        pattern=r"(?:<workspace>/collin_integration_tests/)?(?:collin_integration_tests/)?local_files/feature-requests/([A-Za-z0-9._-]+)\.md",
        repl=r"<feature-requests-root>/\1/request.md",
        string=output,
    )
    output = re.sub(
        pattern=r"prompts/feature-requests/([A-Za-z0-9._-]+)\.md",
        repl=r"<feature-requests-root>/\1/request.md",
        string=output,
    )
    output = output.replace(
        "collin_integration_tests/local_files/feature-requests/", "<feature-requests-root>/"
    )
    output = output.replace("local_files/feature-requests/", "<feature-requests-root>/")
    output = output.replace("prompts/feature-requests/", "<feature-requests-root>/")
    output = re.sub(
        pattern=r"local_files/plans/([A-Za-z0-9._-]+)\.md",
        repl=r"<feature-specifications-root>/\1/plan.md",
        string=output,
    )
    output = output.replace("local_files/plans/", "<feature-specifications-root>/")
    output = output.replace("prompts/plans/", "<feature-specifications-root>/")
    output = output.replace("local_files/Jira/<TICKET-ID>/", "<feature-specifications-root>/<ticket-id>/")
    output = output.replace("local_files/Jira/", "<feature-specifications-root>/")
    output = output.replace("prompts/feature_docs/", "<feature-specifications-root>/")
    output = output.replace("local_files/feature_docs/", "<feature-specifications-root>/")
    output = output.replace("local_files/<feature-specifications-root>/", "<feature-specifications-root>/")
    output = output.replace("local_files/<feature-requests-root>/", "<feature-requests-root>/")
    output = output.replace("local_files/docs/", "<workspace>/docs/")
    output = output.replace("local_files/docker_data/", "<workspace>/docker_data/")
    output = output.replace("local_files/prompts/", "skills/")
    output = output.replace("local_files/", "<workspace>/")
    return output


def _replace_project_memory_paths(*, text: str) -> str:
    """Remove workstation-local project-memory paths from copied prompt content."""
    output = re.sub(
        pattern=r"/Users/[^/\s]+/\.claude/projects/[^/\s]+/memory/MEMORY\.md",
        repl="<project-memory>/MEMORY.md",
        string=text,
    )
    output = re.sub(
        pattern=r"~?/\.claude/projects/[^/\s]+/memory/MEMORY\.md",
        repl="<project-memory>/MEMORY.md",
        string=output,
    )
    output = re.sub(
        pattern=r"~?/\.claude/projects-[^/\s]+/memory/MEMORY\.md",
        repl="<project-memory>/MEMORY.md",
        string=output,
    )
    return output


def _render_skill(
    *,
    spec: SkillSpec,
    prompts_root: Path,
    current_output_path: Path,
    source_to_output_relpath: dict[str, str],
) -> str:
    """Render the committed markdown for one skill."""
    raw_body = _read_source_body(spec=spec, prompts_root=prompts_root)
    title = _derive_title(spec=spec, raw_body=raw_body)
    stripped_body = _strip_first_heading(raw_body=raw_body)
    sanitized_body = _sanitize_body(
        body=stripped_body,
        spec=spec,
        prompts_root=prompts_root,
        current_output_path=current_output_path,
        source_to_output_relpath=source_to_output_relpath,
    )
    examples = _build_examples(spec=spec)
    artifact_block = _build_artifact_paths_block() if spec.slug in ARTIFACT_PATH_SKILLS else ""

    frontmatter: dict[str, str] = {
        "name": spec.slug,
        "description": spec.description,
        "when_to_use": spec.when_to_use,
        "group": spec.group,
        "kind": spec.kind,
    }
    if spec.source_rel:
        frontmatter["source_prompt"] = spec.source_rel
    frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    lines: list[str] = [
        "---",
        frontmatter_text,
        "---",
        "",
        f"# {title}",
        "",
        "## Skill summary",
        "",
        f"- **Name:** `{spec.slug}`",
        f"- **Description:** {spec.description}",
        f"- **When to use:** {spec.when_to_use}",
        f"- **Group:** `{spec.group}`",
        f"- **Kind:** `{spec.kind}`",
    ]
    if spec.source_rel:
        lines.append(f"- **Source prompt:** `{spec.source_rel}`")

    lines.extend(
        [
            "",
            "## Examples",
            "",
            *(f"- {example}" for example in examples),
            "",
        ]
    )

    if artifact_block:
        lines.extend([artifact_block, ""])

    lines.extend(
        [
            "## Guidance",
            "",
            sanitized_body.rstrip(),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_skills(*, specs: dict[str, SkillSpec], prompts_root: Path, skills_dir: Path) -> None:
    """Render and write every committed skill file."""
    source_to_output_relpath = {
        spec.source_rel: _skill_repo_relpath(spec=spec).as_posix()
        for spec in specs.values()
        if spec.source_rel is not None
    }

    for entry in skills_dir.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)

    for spec in specs.values():
        current_output_path = _skill_repo_relpath(spec=spec)
        destination = skills_dir.parent / current_output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        rendered = _render_skill(
            spec=spec,
            prompts_root=prompts_root,
            current_output_path=current_output_path,
            source_to_output_relpath=source_to_output_relpath,
        )
        destination.write_text(rendered, encoding="utf-8")


def main() -> int:
    """Refresh committed skills from the upstream prompt library."""
    repo_root = _resolve_repo_root()
    prompts_root = _resolve_prompts_root()
    skills_dir = repo_root / "skills"
    specs = _build_skill_specs(prompts_root=prompts_root, skills_dir=skills_dir)
    _write_skills(specs=specs, prompts_root=prompts_root, skills_dir=skills_dir)
    print(f"refreshed {len(specs)} skills from {prompts_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
