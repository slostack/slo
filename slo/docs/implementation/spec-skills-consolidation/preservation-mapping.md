> Follow-up contract update: the user now explicitly requires overview/product framing
> AND separate standalone engineering sub-specs for every feature. Prior mode labels,
> tiny-feature combination and partial-family exceptions below describe historical
> baseline instructions, not current policy. Their removal is authorized, not an
> accidental preservation loss. See `family-portability-evidence.md`. Skill locations
> now follow runtime discovery and supported environment overrides.

# Preservation mapping — baseline ea8601c

Prepared BEFORE skill edits. Git paths below are relative to the worktree root,
not the application cwd. Sources were inspected with `git show ea8601c:slo/...`.
P = `slo/skills/design-and-analysis/feature-specifications-pre-hook/SKILL.md`
(393 lines); A = `slo/skills/design-and-analysis/feature-specifications/SKILL.md`
(448 lines); S = `slo/skills/design-and-analysis/feature-specifications-post-hook/SKILL.md`
(390 lines). Destinations below are headings in the existing A file unless
otherwise stated. This is an instruction inventory, not a keyword equivalence claim.

## Baseline drift and resolution contract

1. P/A require one family (overview + technical sub-specs), while workflow and
   breakdown use Mode A/B. Preserve the mode names as compatibility vocabulary:
   Mode A means overview/product framing; Mode B means engineering child slice.
   They select the artifact being authored, not mutually exclusive feature shapes.
   Both halves remain required except tiny combined documents or explicit partial asks.
2. A calls verification legacy/on-request; its mandatory POST hook nevertheless
   invokes it, and workflow Step 2 repeats it independently. Resolve by retaining
   a complete author self-audit (including requirements, architecture, flows/errors)
   inside A; invoke independent verification once after author READY, at workflow
   Step 2 or as a standalone handoff. No self-review is labelled independent.
3. All three defaults use environment/home paths; workflow and project CLAUDE use
   repo-local `specifications/`. State precedence: explicit user choice, project
   override, environment defaults, home fallback. Here CLAUDE's repo-local symlink
   wins. Request `request.md` remains legal only in request artifacts.
4. POST granularity calls task breakdown before independent verification. Retain
   its dependency/split analysis inside self-check, with provisional local slices;
   final task breakdown and any external publication occur only after independent
   verification/approval. No recursive authoring → breakdown → authoring loop.
5. Python examples remain Python; shared design guidance uses Go/TS idioms rather
   than imposing Python syntax. Existing hard extraction and gateway rules remain.

## Detailed instruction inventory and canonical destinations

| ID / baseline | Substantive instructions retained (including examples and gates) | Canonical destination / deduplication |
|---|---|---|
| P1 P:1–30; A:1–35; S:1–30 | Discoverable metadata; author triggers write/generate/spec out; revision triggers; examples | A frontmatter, Skill summary, Examples, Guidance; old hook files compatibility pointers only |
| P2 P:31–52; A:37–81; S:31–52 | Env request/spec roots, one feature folder, request.md vs overview.md, numbered slices, plan.md, installed/repo/personal discovery; humans-first style | Artifact paths and compatibility vocabulary (one definition, both example trees) |
| P3 P:56–75; A:85–95; S:56–78 | Mandatory context before first draft, synthesis in conversation; fetch referenced issue first; mandatory self-check immediately after every draft/revision and before commit/wiki/developer/tasks/implementation | Guidance; Gather context; Self-check; Revise and hand off |
| P4 P:77–89; A:52–59 | Global/repo CLAUDE/AGENTS/SLO, RESEARCH and project MEMORY, ordered reading, record constraining guardrails | Gather context / Load guardrails |
| P5 P:91–126; A:97–114; S:80–97 | One family, both halves, tiny exception, explicit partial ask and inference; overview behavior/journeys/multilayer/traceability/rollout vs slice/boundary/refactor/deletion/wiring; Producing examples; structure mismatch automatic REVISE and STRUCTURE GAP template | Draft / One specification family; Gather / Declare artifacts; Self-check / Confirm artifacts |
| P6 P:128–153 | KB discovery non-blocking, entry point, relevant index/entries and README failure tables; absent KB message/offer/bundle; illustrative eight-row surface→folder table | Gather context / Load Knowledge Base context |
| P7 P:155–188 | Read not just names; domains/services/routers/workers/agents/frontend/DB/integrations/deployment/specs; path+role+convention+truth classification; extra current-state, stale design, standalone facts inventories | Gather context / Inventory affected surface |
| P8 P:190–214; A:209–226; S:194–240 | Behavior-based existing-owner search for every artifact including config/CLI/stores; whole/partial/adjacent classification, file:line evidence, explicit no-owner finding; delete+replace/encapsulate/re-design; deletion/calls/migration/backfill, boundary prose+comments/docstrings+interface; mandatory even greenfield, unresolved redundancy REVISE | Gather context / Find existing owners (inventory); Draft / DRY design (single definition); Self-check / DRY consolidation (independent author re-search and REDUNDANCY GAP template) |
| P9 P:216–243 | Every matching build convention, full 19 mappings including gateways, APIs/Swagger, DBOS, ClickHouse, Alembic, tests, always-on and Vue/TS | Gather context / Read matching conventions; retain mapping list |
| P10 P:245–263 | Concrete scale/throughput, latency, concurrency/idempotency, logs/observability, errors, security/auth, lifecycle, naming, tests, deployment, cross-repo; require coverage or explicit deferral | Gather context / Capture second-order requirements |
| P11 P:265–310 | O'Reilly opening, Changes vs Description, upstream→owned→downstream, existing tree, broad→file→component, prose before code nouns, grouped decisions, journey, control flow, full samples; overview business/scope/non-goals/lifecycle/stakeholders; child metadata/why/current/approach/nouns/flow/order/commands/smoke/unchanged/stale/local facts | Gather context / Plan narrative; canonical definitions in Draft |
| P12 P:312–393 | Full Context Bundle template: source ask, producing, file:line inventory, conventions, scale/latency/logging/idempotency/tests/deploy, consolidation candidates/no owner/boundaries, KB lessons, blocking questions, every narrative field; child current truths/stale text/standalone/order/commands/smoke/unchanged extension; pause for material questions; every section traces to bundle or labelled assumption | Gather context / Synthesize context bundle; preserve PRE-Hook Context Bundle as legacy artifact label |
| A1 A:116–141; S:107–165 | Context opening in order Changes/Description, 1–2 paragraph Big Picture, full existing tree where relevant, broad→narrow changes; named ambiguity/bug/critical resolutions; grouped callout, no § prose, nouns before code; NARRATIVE GAP template; absent/stub/wrong mandatory sections REVISE | Draft / Shared opening requirements; Self-check / Narrative and structure audit (criteria referenced, quality thresholds and template retained) |
| A2 A:143–168 | Overview, Existing Feature (today/challenges/needed/changes), Full Feature Walk Through (visual journey + issue connector/access + traceability), Brief Technical Overview (class/method map + dependency-ordered children) | Draft / Canonical structure |
| A3 A:170–207; S:136–157 | Standalone engineering chapter; boundary, full rigor, no flipping parent, repo numbering; metadata seven fields; both title examples; ten numbered sections, Why/Current/Approach/Nouns/Flow/Details/Tests/Acceptance/Dependencies; isolated unit + real functional flow from true entry point, not shallow mocks | Draft / Canonical structure; Self-check / Narrative and structure audit checks against it |
| A4 A:228–242 | Restate surrounding journey and owned slice; exception purely cross-cutting; each nontrivial hot path every middleware/private helper/commit/external call, one-sentence atomicity guarantee; domain-only omission | Draft / Journey and flow sections |
| A5 A:244–268 | Symptom/concise cause → ideal end-to-end walkthrough → pinpoint break; all specs ideal before change; real faithful source + file:line on ideal and problem; no isolated broken-flow opening | Draft / Ideal behavior and bug analysis (deduplicate two definitions, preserve ordered three-part example) |
| A6 A:270–296; S:271–315 | 1–3 prose sentences before code; no silent code or silent prose; actual source citation; central class docstring/public entry/core helpers; helper what/who/when; named args/types/declarative/Google docs/real values, imports where needed; full corrected child-local example; overview models/DAOs/service/endpoints/workflow/API/tests vs child full listings/stale correction/order/commands/smoke; EXAMPLE GAP template | Draft / Code reference rules; Self-check / Example richness audit |
| A7 A:298–349 | Professional conversational direct voice, we optional, terms introduced, active scannable varied sentences/transitions, concrete paths/values, before-after, useful parentheses, sequence bullets; grouped callout Runtime/Documentation/Testing labels; inline literals, full trees before+after, numbered steps, tables, fenced language, file paths | Draft / Writing style; Visual aids and formatting |
| A8 A:351–395 | Files/components/dependencies/triggers/errors/config/tests/format/lint/smoke; child unchanged/stale/correction; snake_case/PascalCase/kebab URLs/slugs, stable terms, typed fields/IDs, YYYY-MM-DD, explicit heading/path references | Draft / Implementation guidance; Consistency rules (language conventions qualify Python naming) |
| A9 A:397–416; A:435–448 | 16 principles and AI checklist: completeness/clarity/context/practicality/traceability/scannability/progression/disclosure/low ambiguity/both halves/standalone/drift/source/ideal/DRY/single owners; developer at 2am test | Draft / Key principles; absorbed repeated AI summary through explicit application checklist |
| A10 A:418–433 | Implementation details most important contract; MUST read packaged sample; placement+why, every symbol/change/call/interface, behavior all branches/types/state/ownership/config/errors/order/idempotency/unchanged, order/signatures/full examples, real source/stale/consolidation, exact tests+fixtures+assertions+levels+commands+smoke; vague update/add tests/handle errors fails; two plausible choices → revise | Draft / Implementation details are the implementation contract; Self-check release gate |
| S1 S:99–105 | Full formal verification coverage, not just-wrote-it exemption; findings feed revision | Self-check / Requirements architecture and failure audit (complete author-owned procedure); separate independent skill invoked only after author READY |
| S2 S:167–192 | Layer audit app invoke/session, domain files/relationships/index/Pydantic, router schema/auth/registration, workers registration/idempotency/retry/payload/schedule, events constant/schema/pub/sub, tools files/prompts/gateway, clients auth/retry/errors/config, Alembic/model registration, style/tests, structured logging/correlation; CONVENTION GAP template | Self-check / Convention audit |
| S3 S:242–269 | Split triggers >~3 layers, >1 domain, backend+frontend+deploy, >~10 steps, >~15 requirements, independently shippable stakeholders; broad overview allowed, narrow standalone children; dependency ordered tasks + parent/child restructuring; no split OK text | Self-check / Granularity check; Revise handoff to final separate breakdown after verification |
| S4 S:317–343 | Every modified method decisions/per-branch tests/fixtures/mocks/negative paths; controller stack, app/domain namespaces, visible integration/BDD, branch names; TEST GAP template | Self-check / Test coverage validation |
| S5 S:345–379 | Aggregate all findings; report artifact/JIRA coverage/layers/narrative/convention/redundancy/example/test/granularity/verdict; automatic REVISE narrative/redundancy/structure/missing half/mandatory child/prose; edit and rerun until READY; post report and stop | Revise and hand off; retain POST-Hook Report alias |
| S6 S:381–390 | READY next ask commit/publish/tasks/implementation/developer; preserve report in conversation/PR for next reviewer | Revise and hand off; independent review prerequisite and publication confirmation explicit |

## Independent review and workflow boundaries

- Verification retains all Steps 1–7, requirement extraction/status matrix,
  nine-layer checklist, flow/state/cross-repo/error audit, independent owner searches,
  severity/templates/review-of-review and implementation-details CRITICAL gate.
- Workflow retains every substantive paragraph, manual/auto pause, outputs,
  dependency/traceability handoff, CRITICAL return loop and exit conditions. Only
  hook names, mode mapping and necessary integration wording change.
- Breakdown retains examples, code exactly once, dependency graph, JIRA procedures,
  constraints and quality checklist; provisional split does not authorize publication.

## Depth addition coverage

Canonical destination: coding/declarative-method-structure `Module-depth design guidance`.
Consumers: author Self-check `Caller-burden check`; review-feature-code Step 6
`Module-depth design review`. Meaningful outcomes; constructors/order/flags/errors;
owned complexity; internal evolution; one invoke insufficient; cohesive private steps;
required thin boundaries and gateways; no wrappers/god objects/security weakening;
retry/cancellation/durability/error caller contract; advisory evidence not automatic
blocker or ~8-line exemption; Python/Go/TS idioms equally. Independent review pending.

## Verification status

The table was written before edits. Manual comparison now completed against all three
baseline bodies: retained context fields, example trees, numbered structures, gap
formats, threshold triggers and READY conditions. Duplicate path/family/DRY definitions
were replaced by references; repeated narrative criteria remain as audit checks (not
second definitions). Formal verification's complete checklist is referenced for the
author-owned audit and still executed independently at workflow Step 2. The AI-summary
bullets are absorbed by Draft's 16 principles and explicit requirements; no separate
competing summary owner. Keyword tests are supporting discovery contracts, not proof
of semantic preservation. Independent Step 2 must challenge this manual assessment.

## Exact final heading destinations

All entries below are in `slo/skills/design-and-analysis/feature-specifications/SKILL.md`.
These line numbers supplement the semantic destination headings above.

- L10: `# Feature Specifications`
- L12: `## Skill summary`
- L20: `## Examples`
- L26: `## Guidance`
- L42: `## Artifact paths and compatibility vocabulary`
- L88: `## Gather context`
- L90: `### 1 — Load global guardrails`
- L109: `### Declare artifacts`
- L118: `### 3 — Load Knowledge Base context`
- L145: `### 4 — Inventory the affected surface area`
- L169: `### Extra requirement when producing a technical sub-spec`
- L180: `### 4.5 — Identify redundancy and consolidation candidates`
- L203: `### 5 — Read the matching code-convention prompts`
- L232: `### 6 — Capture second-order requirements`
- L252: `### 7 — Plan the human-readable narrative sections`
- L270: `### Extra planning requirements for the overview`
- L280: `### Extra planning requirements for a technical sub-spec`
- L299: `### 8 — Synthesize the context bundle`
- L350: `### Additional required bundle content when producing a technical sub-spec`
- L378: `### Context handoff`
- L382: `## Draft`
- L384: `### One Specification, Product Framing *and* Engineering Detail Together`
- L402: `### Shared Opening Requirements`
- L404: `### Mandatory opening section: `## Context``
- L421: `### Additional mandatory opening rules`
- L429: `### Canonical Structure`
- L433: `### The `overview.md` — product framing and technical map`
- L456: `### The technical sub-specs — one standalone engineering chapter per slice`
- L495: `### DRY Design: No Redundant Artefacts, Entities, or Domains`
- L514: `### Journey and Flow Sections`
- L516: `### `## Full Feature Walk Through` and the journey it owns`
- L522: `### `## Control Flow: <hot-path-name> (Step-by-Step)``
- L529: `### Ideal Behavior First, Then the Problem — With Real Code`
- L543: `### `## Code Reference` Rules`
- L571: `### Writing Style`
- L573: `### Tone & voice`
- L582: `### Sentence structure`
- L589: `### Clarity techniques`
- L596: `### Call-outs`
- L604: `### Visual Aids & Formatting`
- L624: `### Implementation Guidance`
- L647: `### Consistency Rules`
- L670: `### Key Principles`
- L691: `### Important: Implementation Details Are the Implementation Contract`
- L708: `## Self-check`
- L710: `### Requirements architecture and failure audit`
- L732: `### Caller-burden check`
- L745: `### Check 0 — Confirm which artefact(s) the draft covers`
- L763: `### Check 1.5 — Human-readable narrative and structure audit (mandatory)`
- L767: `### Shared opening audit (overview and every sub-spec)`
- L782: `### Overview audit — product framing`
- L792: `### Technical sub-spec audit — engineering structure`
- L823: `### Check 2 — Cross-check the spec against the code-convention prompts`
- L850: `### Check 2.5 — DRY consolidation pass (mandatory)`
- L854: `#### 2.5.1 — Inventory what the spec introduces`
- L858: `#### 2.5.2 — Search the code for the same or adjacent responsibility`
- L871: `#### 2.5.3 — Consolidate`
- L889: `### Check 3 — Granularity check`
- L902: `### Structure-aware split guidance`
- L918: `### Check 4 — Example richness audit`
- L924: `### Shared example expectations`
- L934: `### Overview emphasis`
- L944: `### Technical sub-spec emphasis`
- L964: `### Check 5 — Test coverage validation`
- L992: `## Revise and hand off`
- L1034: `### Handoff`

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
