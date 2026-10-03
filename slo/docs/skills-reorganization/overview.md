# 87 — Multi-language skills reorganization

## Authorization and baseline

The supplied `87-skills-reorganization/request.md` requested a subsequent design before migration. This document records that design before changes; the current user request explicitly authorizes creating the replacement library. Worktree: `feature-87-skills-reorganization`, based on fetched `origin/main` at `f63df0a`. No release stability beyond that branch tip is inferred. Atlas and installed user files are read-only references.

## Inventory and current discovery

`inventory.json` records every bundled and installed-user source, SHA-256, skill description and section headings (including non-SKILL resources), plus Atlas conventions and atlasd source/test evidence. This is a source/section inventory, not a claim that hashes prove semantic equivalence.

Runtime `SkillsLoader.load_merged` recursively loads bundled skills, user skills, then user workflows. Same-name user entries override bundled entries. Its prompt XML exposes name, description, absolute location; **when_to_use and arbitrary YAML scope fields are not exposed**. `SkillRegistry` is a separate development-time index generator. Project instructions are read through workspace context/orientation, not a fourth skill-loader tier. User-owned skills must not be overwritten or removed. New Go canonical names use `go-...` names distinct from legacy `build-go-...` and `golang-coding-conventions`, with a migration table. Retained TypeScript names may be shadowed by installed copies; the routing guide must make that visible. File publication is not runtime enforcement of selection.

## Target taxonomy and authority

- `engineering/`: language-independent ownership, verification, review and routing.
- `languages/python/`: complete existing Python recipes, explicit Python applicability, one conventions entry point.
- `languages/go/`: authoritative conventions and focused component/testing recipes; optional stack recipes explicitly gated.
- `languages/typescript/`: installed detailed TypeScript guidance, with scoped conventions entry point.
- Existing `frontend-vue/`, CLI, TUI, integration, git, presentation, orientation and design/workflow paths stay stable. They are framework/task families, not universal language rules.
- `coding/` legacy paths become forwarding skills, not second copies of rules. Moved skill names stay stable at their canonical location; forwarding entries have distinct names and are excluded from model invocation.

One requirement has one authoritative owner. Shared obligations are translated by language conventions; framework recipes specialize construction, not weaken coverage. User/project decisions can explicitly approve deviations; locality or recency alone cannot waive baseline obligations. Stop and identify both authorities when intent cannot be resolved. Guidance must distinguish architecture from optional dependency choice. No forced Go ORM/HTTP framework or Python framework for unrelated tasks.

## Reconciliation decisions

| ID | Conflict | Resolution / authority |
|---|---|---|
| R1 | Go root test-first vs cadence code-first | Root §14.6 explicitly says always test first: Go uses red → green → refactor. Shared cadence requires small verified increments and defers ordering to language. |
| R2 | Recording fakes vs real collaborators | Separate orchestration-unit, adapter/database integration, and end-to-end categories. Fakes prove order/cutoffs; real stores prove constraints/rollback. Neither substitutes for the other. |
| R3 | Provider/exported interfaces, positional construction, partial runtime | Atlas CONVENTIONS §§1–9 and updated root §14 supersede old examples. Consumer-local lowercase interfaces, named construction DAOs, resolved runtime publication, supervised ownership. Rewrite conflicting Go core examples rather than placing a disclaimer above contradictory code. |
| R4 | Python tests summary says mocks/TestClient | Correct to real-domain transactional integration and httpx.AsyncClient respectively; retain detailed harness. |
| R5 | Universal Python keywords/docstrings/invoke/pytest | Move to Python authority; shared workflows route by language and project commands. |
| R6 | Atlas main help prescan/public daemon internals vs conventions | Atlas source is style evidence (thin CLI, output/error tests), not permission to preserve deviations. No normative help prescan, mutable service locator or global config singleton. |
| R7 | Go stack overview vs configuration skill | Go CLI config skill owns config-only pflag/viper choice; other framework dependencies are scoped recipes, never automatically selected for all Go. |
| R8 | Domain DAO used as repository vs transient data | DAO owns transient boundary data; persistence adapter/repository owns database mechanics. Single-domain transactions may belong to domain owner; cross-domain atomicity belongs to application service. |
| R9 | User overrides | Preserve loader semantics and user content; report source collision and load canonical renamed Go entry. Do not silently rewrite the user's installation. |

## Incremental implementation and preservation

1. Record inventory/design and regression tests.
2. Move complete Python bodies without truncating recipes; correct known misleading scope/summary text. Keep compatibility forwarding paths and links.
3. Import TypeScript and Go sources with provenance. Reconcile core Go examples and add lifecycle, ownership, review, security and codec detail. Keep detailed optional-stack recipes, with explicit prerequisites and companion authorities.
4. Add shared engineering/router entries and per-language conventions. Route workflows through these without moving canonical workflow paths or dropping stages, PRE/POST hooks, revision loops, confirmations or detached/in-session semantics.
5. Rebuild index; prevent legacy refresh from deleting curated families. Validate discoverability, links, coverage mappings, workflows, loader overrides and packaged content.

## Verification contract

Tests must cover inventory destination existence; preserved bundled recipes and workflow resources; unique canonical names; parseable frontmatter; metadata applicability; link integrity for concrete skill paths; index reproducibility; installed override behavior; representative positive/negative routing contracts (Go lifecycle without Gin/Postgres, Python FastAPI, Vue composable, mixed review, unsupported language); workflow stage/artifact/revision handoffs; and package inclusion. Routing tests check published contracts and runtime metadata, **not actual model obedience**. Run existing skills, prompt, workflow, loader and packaging tests, then full non-e2e suite when feasible. Record exact commands/results and limitations. Do not claim semantic no-loss or stellar runtime behavior merely from file counts.
