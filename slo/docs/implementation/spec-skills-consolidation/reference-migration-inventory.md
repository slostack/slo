# Reference migration inventory

## Audited surfaces

Baseline `ea8601c`; application-relative paths below. Searched tracked skills,
scripts, tests, docs, packaging with `git grep`, and all personal Markdown read-only
with `grep -R -n -E 'feature-specifications|declarative-method-structure|review-feature-code' "$SLO_USER_SKILLS_DIR" --include='*.md'`.
No personal hook/verification references were found. No external writes were made.

| Caller / owner | Migration / disposition |
|---|---|
| feature-specifications/SKILL.md | Sole authoring owner, kind=skill; four stages; old report labels retained as aliases |
| feature-specifications-pre-hook/SKILL.md | Compatibility redirect to `#gather-context`, kind=skill |
| feature-specifications-post-hook/SKILL.md | Compatibility redirect to `#self-check` and `#revise-and-hand-off`, kind=skill |
| workflows/specification-development.md | Exactly author → independent review → breakdown; names and integration wording only; manual/auto, publication confirmation, READY/CRITICAL loops retained |
| specification-development/SKILL.md | Still pointer to formal workflows/ file; updated stage list |
| workflows/SKILL.md | Updated skill roster and REVISE example; routing unchanged |
| orchestrator/SKILL.md | Draft-only route loads canonical author; no promotion/routing-policy change |
| implement-feature-request/SKILL.md | Updated skill chain, formal workflow pointer unchanged |
| orientation/readme/SKILL.md | Context reference canonical; old entries clearly compatibility-only |
| feature-specification-verification/SKILL.md | Independent/standalone role clarified, canonical paths/modes reference; complete Steps 1–7 remain |
| breakdown-feature-spec-to-tasks/SKILL.md | Canonical paths/modes reference and author-report terminology; breakdown procedure retained |
| gather-feature-context/SKILL.md | Previously claimed default PRE role despite author calling it on-request; now explicitly optional extended briefing feeding required context bundle |
| review-feature-code/SKILL.md | Canonical depth anchor and caller-burden review; hard-rules post-hook untouched |
| coding/declarative-method-structure/SKILL.md | Canonical depth guidance; existing hard extraction rule retained |
| scripts/refresh_skills.py | Local-policy allowlist; refresh no longer deletes directories, so local workflows/samples survive. Upstream-owned records still render normally. Old hook names in classification sets remain compatibility metadata, not operational invocation |
| scripts/build_skill_index.py | Unchanged established generator; executed via make build-skill-index |
| skills/INDEX.md | Regenerated; 117 discoverable names retained, hook descriptions identify redirects |
| pyproject.toml | Existing `skills/**/*` wheel/sdist inclusion covers canonical/redirect/workflow/sample files; no packaging change required |
| tests/agents/skills/test_specification_authoring.py | New routing/redirect/anchor/index/depth/refresh regression contracts |
| samples/implementation-details-granularity.md | Historical source-code/metadata specimen, not operational authoring caller; retained as required granular sample |
| workflows/code-test-review.md and code-test-review/SKILL.md | Unchanged; Step 1 execution only |

## Why redirects remain

Actual baseline evidence: refresh manifest classification, orchestrator, implementation
workflow caller, orientation guide and generated index all published both hook names.
Installed older copies can still call these names even after vendored callers migrate.
Keeping small redirects avoids breaking those consumers; neither carries a second
procedure. No speculative migration of user-owned files or new skill is necessary.
No anchored hook callers were found. Canonical new anchors are validated by tests.

## Personal skill audit and migration needs

- `README-go-skills.md:38` maps Go conventions to declarative-method-structure;
  `:91` refers to review-feature-code. Both names remain valid.
- `golang-coding-conventions/SKILL.md:40` references Python declarative structure.
  The canonical name remains valid. Its ~15-line Go rule is not rewritten; depth
  grants no exemption from applicable language-specific hard rules.
- TypeScript declarative skill keeps its ~8-line extraction rule and typed options
  companion. No personal file points to a removed authoring path.
- No required personal migration for compatibility. Optional future user-authorized
  migration: add the canonical module-depth anchor to Go/TS personal guides. Until
  then vendored author/reviewer guidance explicitly covers all three languages and
  asks readers to load those personal conventions. Never silently overwrite them.

## Tooling behavior note

Refresh is now a non-destructive overlay for upstream-owned skills; stale upstream
files are not automatically pruned. Removal requires a deliberate reviewed change.
This avoids losing local formal workflows, sample artifacts and authoritative policy.
Full upstream regeneration was NOT run (would change unrelated policy); isolated
real writer tests exercise both preservation and ordinary upstream rendering.

## Final-dispatch Step 1 correction (independent re-review pending)

G1/G2 corrections and the bounded refresh-ownership audit are recorded in
`revision-evidence.md`. Refresh now protects the Code-Test-Review pointer and
audited local routing/review/KB safety policies via the existing ownership set.
The real manifest/writer test asserts byte preservation and a genuine same-path
upstream replacement. This is not a universal preservation claim for all historical
customizations. No formal Code-Test-Review policy was edited.

The extended context companion now advertises its on-request role in runtime and
registry metadata, summary, examples and purpose; it references the canonical
artifact-path owner. Its source-retention, schema, briefing and sign-off procedure
is retained. N1 qualifies shared documentation checks by language; N2 covers all
migrated caller links. Canonical author stages, substantive audit gates, depth
qualifications and independent verification/breakdown boundaries remain unchanged.
Historical line numbers above describe the earlier receipt; headings remain the
semantic destination authority. Independent Step 2 re-review and Step 3 remain
PENDING, not performed by this correction agent.

Follow-up: resolve the personal-skill directory from `config.cfg.USER_SKILLS_DIR` when the override is unset; never assume a host-specific install path.
