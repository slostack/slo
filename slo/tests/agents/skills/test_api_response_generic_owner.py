"""Focused contract tests for the generic API-response skill owner."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.agents.skills.registry import SkillRegistry
from src.agents.slo_agent.skills.service import SkillsLoader

ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = ROOT / "skills/coding/api-response-conventions/SKILL.md"
INDEX_PATH = ROOT / "skills/INDEX.md"
PYTHON_RECIPE_PATH = ROOT / "skills/languages/python/api-response-conventions/SKILL.md"
GO_RECIPE_PATH = ROOT / "skills/languages/go/go-recipe-api-response-conventions/SKILL.md"
TYPESCRIPT_RECIPE_PATH = ROOT / "skills/languages/typescript/typescript-api-response-conventions/SKILL.md"
TYPESCRIPT_MIDDLEWARE_PATH = ROOT / "skills/languages/typescript/typescript-build-middleware/SKILL.md"
TYPESCRIPT_REVIEW_PATH = ROOT / "skills/languages/typescript/typescript-code-review-rules/SKILL.md"


def _skill_text() -> str:
    """Return the authored generic API-response skill text."""
    return SKILL_PATH.read_text(encoding="utf-8")


def test_generic_owner_has_canonical_identity_and_no_legacy_metadata() -> None:
    """The approved coding path is the active generic owner, not a disabled forwarder."""
    text = _skill_text()
    metadata = yaml.safe_load(text.split("---", 2)[1])

    assert metadata == {
        "name": "api-response-conventions",
        "description": metadata["description"],
        "when_to_use": metadata["when_to_use"],
        "group": "coding",
        "kind": "skill",
    }
    assert "disable-model-invocation" not in metadata
    assert "disable-model-invocation" not in text
    assert "source_prompt" not in metadata
    assert "legacy-api-response-conventions" not in text
    assert "D1" not in text
    assert "D2" not in text
    assert "N1" not in text
    assert "approval questions" not in text.lower()


def test_generic_owner_describes_contract_and_scoped_profiles() -> None:
    """The generic body states stable semantics without selecting conflicting profile values."""
    text = _skill_text()

    for phrase in (
        "{data, api_version, errors}",
        "Profiles override these defaults",
        "wire bytes",
        "counts",
        "field names",
        "page bases",
        "version formats",
        "error shapes",
        "error codes",
        "do not silently resolve",
        "documented project profile",
        "report any unresolved disagreement",
        "Existing Atlas and Sentinel profiles",
    ):
        assert phrase in text


def test_generic_owner_has_substantive_same_profile_examples_in_all_languages() -> None:
    """Each language sample independently uses the same illustrative profile."""
    text = _skill_text()

    expected_sections = {
        "### Python — illustrative typed envelope and serialization": (
            "from dataclasses import",
            'api_version="v1.0"',
            "data=None",
            'code="NOT_FOUND"',
            "page=0",
            "size=25",
            "total=1432",
            "items=[User(",
        ),
        "### Go — illustrative typed envelope and serialization": (
            "type ResponseErrors struct",
            'APIVersion: "v1.0"',
            "Data: nil",
            'failure[User]("User not found", "NOT_FOUND")',
            "Page: 0",
            "Size: 25",
            "Total: 1432",
            "Items: []User",
        ),
        "### TypeScript — illustrative typed envelope and serialization": (
            "type ResponseErrors = {",
            'api_version: "v1.0"',
            "data: null",
            'code: "NOT_FOUND"',
            "page: 0",
            "size: 25",
            "total: 1432",
            "items: [{ id:",
        ),
    }
    for heading, markers in expected_sections.items():
        section_start = text.index(heading)
        next_heading = text.find("\n### ", section_start + len(heading))
        section = text[section_start:] if next_heading == -1 else text[section_start:next_heading]
        for marker in markers:
            assert marker in section, (heading, marker)

    assert text.count("Illustrative sample; not copied from production") == 3
    assert "not executed here" in text
    assert "not compiled here" in text


def test_generic_owner_is_discoverable_and_indexed_as_active_canonical_name() -> None:
    """Registry, runtime loader, and generated index expose both scoped profiles by path."""
    registered = SkillRegistry.load(skills_dir=ROOT / "skills")
    runtime = SkillsLoader.load(skills_dir=str(ROOT / "skills"))
    index = INDEX_PATH.read_text(encoding="utf-8")
    generic_location = "skills/coding/api-response-conventions/SKILL.md"
    python_location = "skills/languages/python/api-response-conventions/SKILL.md"

    assert any(
        entry.name == "api-response-conventions" and entry.location == generic_location
        for entry in registered
    )
    assert any(
        entry.name == "python-api-response-conventions" and entry.location == python_location
        for entry in registered
    )
    assert any(
        entry.name == "api-response-conventions" and entry.file_path == str(SKILL_PATH) for entry in runtime
    )
    assert any(
        entry.name == "python-api-response-conventions" and entry.file_path == str(PYTHON_RECIPE_PATH)
        for entry in runtime
    )
    assert "**api-response-conventions**" in index
    assert "**python-api-response-conventions**" in index
    assert generic_location in index
    assert python_location in index
    assert "**legacy-api-response-conventions**" not in index
    assert "legacy-api-response-conventions" not in index
    assert "disable-model-invocation" not in index


def test_generic_owner_has_no_competing_api_response_contract_path() -> None:
    """The approved generic owner remains at the requested path without a second contract file."""
    competing_paths = [
        path
        for path in (ROOT / "skills").rglob("SKILL.md")
        if "api-response-contract" in path.parent.name or "api-response-contract" in path.stem
    ]

    assert competing_paths == []


def test_generic_owner_states_profile_precedence_and_unresolved_conflict_handling() -> None:
    """Profile values override illustrative defaults, and specific conflicts stay explicit."""
    text = _skill_text()

    assert "Profiles override these defaults on the exact points they document." in text
    assert "Use the documented project profile" in text
    assert "report any unresolved disagreement to the contract owner" in text
    assert "do not silently resolve the conflict by choosing the newest example" in text


def test_generic_owner_links_existing_language_recipes() -> None:
    """The generic owner points readers at the preserved language-specific recipes."""
    text = _skill_text()
    for path in (
        "skills/languages/python/api-response-conventions/SKILL.md",
        "skills/languages/go/go-recipe-api-response-conventions/SKILL.md",
        "skills/languages/typescript/typescript-api-response-conventions/SKILL.md",
        "skills/languages/typescript/typescript-build-routers/SKILL.md",
    ):
        assert path in text


def test_language_recipes_delegate_common_policy_and_retain_adapter_requirements() -> None:
    """Adapters reference the generic owner while keeping concrete wire and framework policy local."""
    python = PYTHON_RECIPE_PATH.read_text(encoding="utf-8")
    go = GO_RECIPE_PATH.read_text(encoding="utf-8")
    typescript = TYPESCRIPT_RECIPE_PATH.read_text(encoding="utf-8")

    for text in (python, go, typescript):
        assert "skills/coding/api-response-conventions/SKILL.md" in text
        assert "data" in text and "api_version" in text and "errors" in text

    assert "SuccessResponseDAO" in python
    assert "success_response(payload=page_dao.model_dump(mode=\"json\"))" in python
    assert "page=0" in python and "size=25" in python and "size <= 100" in python
    assert "success_response()" in python

    assert "type SuccessResponse[T any]" in go
    assert "errors.Is/As" in go
    assert "httptest" in go
    assert "version values and pagination defaults are not automatically interchangeable" in go

    assert "successResponse<T>" in typescript
    assert "apiResponseSchema" in typescript
    assert "satisfies ApiResponse<T>" in typescript
    assert "page 1 and size 20" in typescript
    assert "size default 20" in typescript or "size ?? 20" in typescript


def test_typescript_router_preserves_unknown_profile_as_non_normative() -> None:
    """The router recipe preserves its full example while deferring wire choice explicitly."""
    router = (ROOT / "skills/languages/typescript/typescript-build-routers/SKILL.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "historical, nonnormative framework example",
        "unknown profile",
        "not evidence for Sentinel, Atlas, Slo",
        "For a new TypeScript API",
        "TypeScript API response profile",
        "require an explicit feature/API contract",
        "Response shape follows the selected profile",
        "Historical response-envelope example (unknown profile; nonnormative)",
        "Historical router-file example (Hono; same unknown profile; nonnormative)",
        "The `ok`/`fail` helpers shown in the historical example are not a universal response contract",
    ):
        assert phrase in router

    assert "ApiError[] | null" in router
    assert "api_version" not in router
    assert "data: T | null" in router
    assert "errors: ApiError[] | null" in router
    assert "success sets `data`, failures set `errors`" not in router


def test_typescript_middleware_scopes_historical_response_helpers_to_a_selected_profile() -> None:
    """Middleware mechanics remain useful without defining a universal response wire format."""
    middleware = TYPESCRIPT_MIDDLEWARE_PATH.read_text(encoding="utf-8")

    for phrase in (
        "Response-profile status",
        "ok()`/`fail()` calls and envelope are profile-specific implementation examples",
        "unknown-profile historical framework recipe",
        "not a universal response standard",
        "TypeScript API response profile",
        "language-independent response contract",
        "explicit existing/project contract before changing",
        "owns lifecycle mechanics, not a competing wire format",
        "selected response profile",
        "historical unknown-profile implementation examples",
    ):
        assert phrase in middleware

    assert "into the standard envelope" not in middleware
    assert "ApiError[] | null" not in middleware
    assert "return ctx.json(ok(user));" in middleware
    assert "return ctx.json(fail('INTERNAL_ERROR', 'An unexpected error occurred'), 500);" in middleware


def test_typescript_review_rules_scope_envelope_examples_to_unknown_or_selected_profiles() -> None:
    """Review rules preserve examples while forbidding an unqualified envelope prescription."""
    review = TYPESCRIPT_REVIEW_PATH.read_text(encoding="utf-8")
    section_start = review.index("### 3.2 All responses follow the selected API response profile")
    section_end = review.index("### 3.3", section_start)
    response_section = review[section_start:section_end]

    for phrase in (
        "selected and documented response profile",
        "TypeScript API response profile",
        "language-independent response contract",
        "existing/project contract before changing",
        "historical or unknown-profile review examples",
        "not a universal standard",
        "do not define an additional TypeScript profile",
    ):
        assert phrase in response_section

    assert "standard envelope" not in review
    assert "res.json({ data: user });" in response_section
    assert 'error: { code: "VALIDATION_ERROR", message: err.message }' in response_section
    assert "All responses follow the selected/project API response profile" in review


def test_generic_owner_cross_references_typescript_router_conflict() -> None:
    """The generic owner points to the router and states the explicit-contract boundary."""
    generic = _skill_text()
    router = (ROOT / "skills/languages/typescript/typescript-build-routers/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "typescript-build-routers/SKILL.md" in generic
    assert "preserved unknown-profile historical response example is nonnormative" in generic
    assert "must not be silently merged into this contract" in generic
    assert "unknown profile" in router
    assert "explicit feature/API contract" in router


def test_naming_owner_is_language_neutral_and_go_constructor_rule_is_scoped() -> None:
    """Generic naming teaches lifecycle ownership; Go owns the newX spelling."""
    naming = (ROOT / "skills/coding/naming-and-clarity/SKILL.md").read_text(encoding="utf-8")
    go = (ROOT / "skills/languages/go/go-conventions/SKILL.md").read_text(encoding="utf-8")

    assert "background execution/concurrency" in naming
    assert "Spawns goroutines?" not in naming
    assert "goroutine" not in naming
    assert "Python" in naming and "Go" in naming and "TypeScript" in naming
    assert "Idiomatic Go `newX`" not in naming
    assert "`newX` used only for small single-object constructors?" not in naming
    assert "package-private constructor form `newX`" in go
    assert "Use `newX` for small single-object constructors" in go
    assert "not a language-independent lifecycle rule" in go


def test_generic_api_owner_keeps_language_syntax_in_illustrative_examples_only() -> None:
    """The generic API owner delegates implementation syntax while retaining shared semantics."""
    api = _skill_text()
    go_example_start = api.index("### Go — illustrative typed envelope and serialization")
    go_example_end = api.index("### TypeScript — illustrative typed envelope and serialization")
    go_example = api[go_example_start:go_example_end]
    before_examples = api[:go_example_start]

    assert "Illustrative sample; not copied from production" in go_example
    assert "type APIResponse[T any]" in go_example
    assert "The applicable adapter or project profile owns" in api
    assert "Gin/net/http" not in before_examples
    assert "Pydantic/FastAPI" not in before_examples
    assert "Zod" not in before_examples
