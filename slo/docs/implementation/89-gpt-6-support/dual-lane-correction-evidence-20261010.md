# Feature 89 — bounded design correction evidence

**COMPLETE for specification/design only.** Author self-check, not independent code review or feature completion. No production or test file was edited and no application test was run.

## Authority and discovery

Read the complete `/root/Code/specifications/headless-code-test-review.md` first. Its general detached execution direction is bounded by this assignment's explicit no-nested-orchestration and design-only instructions: no launch/spawn and no workflow restart. Formal Code-Test-Review remains Code+Test → independent Review → fresh Completion Assessment, with external-action confirmation. This pass only supplies the corrected implementation contract.

Read AGENTS.md through EOF (continued after tool truncation), root RESEARCH.md, provided full docs/RESEARCH.md, local SLO.md/CLAUDE.md instructions, recovery13-closure.md, discovery-read-receipt-20261010.md, coordinator-checkpoint.md and step1-continuation-handoff.md. All SEVEN canonical specifications were read fully before editing. Earlier setup/main/waiver instructions are not repeated or inferred as current permissions.

Source discovery: `config/cfg.py` and full `src/agents/slo_agent/skills/service.py`. Actual `SLO_SKILLS_DIR` is `/root/.local/share/pipx/venvs/slo/lib/python3.11/site-packages/skills`; `SLO_HOME=/root/.slo`; user skill/workflow overrides unset. Defaults `/root/.slo/user_skills` and `/root/.slo/user_workflows` (absent). User frontmatter names enumerated: none overrides selected conventions. Actual precedence is user workflows > user skills > vendored by frontmatter name, not folder name. No runtime application import was used for discovery.

Resolved formal workflow: that vendored root's `design-and-analysis/workflows/code-test-review.md`, read fully, plus its `design-and-analysis/code-test-review/SKILL.md` pointer. Matching loaded skills: feature-specifications, feature-specification-verification author-audit checklist, code-test-loop, named-arguments-and-type-hints, declarative-method-structure, method-docstrings, test-verification-policy, build-clients, build-application-services and build-textual-tuis. Packaged implementation-details-granularity sample inspected for structure. Specific existing SDK/owner contracts take precedence over generic examples: no new HTTP client, app-service, graph, TUI widget or credential mechanism.

Actual SLO_KB_DIR points to `/root/Code/KnowledgeBase/KB/Welcome.md`; use parent directory. Consulted Welcome, linked slo/README index, gotchas, model-pool-and-rate-limits. Source confirms KB warnings about bound tools, routed identity, no raw replay, and stale path descriptions. No credential/cache/history locations were opened. Shared KB was not edited because outputs are expressly restricted to the existing implementation/evidence directories; durable correction rationale is retained in the handoff for later authorized documentation synchronization.

## Source-grounded design findings

The cause is incorrect catalog policy, not a missing OAuth implementation. Existing seed helper sets False; record checks, session prechecks and picker faithfully propagate that false assumption. Factory already branches on effective OAuth into `build_chatgpt_backed_chat_openai`. Correction is True seed eligibility plus API-key scoping of strict Platform constructor policy, not disabling eligibility or routing OAuth to api.openai.com.

Retain frozen reasoning overrides: default-only change stays permitted, fixed effort/control fields stay protected. Both flags stay in Python merges and excluded only at the schema2 writer. Retain Astra baseline policy/Feature88 merge rule and Jev's complete metadata/null/freshness contract.

Additional source constraint: the real resolver filters fully expired stored tokens. Existing old tests that patch `require` to return expired OAuth cannot prove refresh lifecycle. Correct acceptance uses still-valid near-expiry token + real refresher/store and injected synthetic transport; separately test fully expired missing-auth behavior. No auth semantics redesign.

## Author self-check and traceability

| Requirement | Corrected owner / verification plan |
|---|---|
| Three dual-lane seeds and immutable independent flags | a.1 exact records/copy/merge/override/writer tests; AC1/8/11 |
| Same 21 reasoning cells in both lanes, off and omitted medium | overview/a.1/b.1 tables and two-lane locked SDK matrix; AC2/3/6 |
| Protected Platform remains fixed; OAuth remains existing subscription backend | b.1 lane table, auth_type-aware helper signature/sample, exact Codex headers/store/include/cache/caps/instructions; AC3/4/5/9 |
| Genuine guards, real resolver precedence, atomic failures and refresh | c.1 and e.1 both-lane success, synthetic ineligible negatives, Event-barrier removal/type transitions; AC5/6/8/15 |
| Cached auth/picker/status, switching invalidation and two-size paint | c.1 neutral subscription status in existing owner; both-lane 12 mounted flows; AC7/8 |
| Real tools/result IDs, nonstreaming/streaming, headless/pool/resume | b.1/e.1 explicit matrix and handoff paths; AC3/6/10/14/15 |
| Public facts, Feature88/Astra, Jev null and safety unchanged | overview/d.1 and retained e.1 regression/frozen-reader matrix; AC9–15 |
| No implementation/system/state/external changes | 691-file before/after content preservation manifest; unchanged branch/HEAD; no tests/installs/provider requests |

Catalog, factory/SDK, session/refresh, graph/pool/compaction, TUI, persistence and tests each retain one existing owner. No database/router/worker migration, new API, command, config key or cross-repo service is introduced. Caller burden stays at existing factory/session gateways; only factory's private policy helper receives captured auth type. Lane transport complexity remains inside existing builders/adapters. Author check found no unresolved scope/ownership gap; independent implementation review has not run.

All fifteen ACs remain once each in overview and dependency index. Five children retain numbered sections 1–10, existing filenames, valid sibling links and balanced code fences. Required public numeric metadata and exact none/low matrix retained. Negative eligibility is a distinct synthetic entry; no GPT6 or Astra negative fixture is prescribed. Generic unavailable text still exists intentionally for genuinely denied records.

## Executed documentation checks

- Fresh read-only git branch/HEAD matched requested target; all pre-existing dirty work retained.
- Existing local interpreter metadata: Python3.11.7, OpenAI2.38.0, Pydantic2.13.4, langchain-openai0.3.35, core0.3.86, httpx0.28.1, Textual8.2.8. No installation or PATH changes. These versions match the stated lock; application execution is not implied.
- `.f89-evidence/dual-lane-design-before.json`: SHA256 of 691 source/test/config/support files, branch/HEAD and package versions.
- `.f89-evidence/verify-dual-lane-design.py`: exact seven-file inventory, AC1–15, structure/links/fences/whitespace, both URLs/true flags/reasoning map/public numeric facts, unchanged 691-file content and git identity, git diff --check.
- First document-check attempt rejected the intentionally retained synthetic `supports_chatgpt_codex=False` test text. Corrected the checker to permit only the explicitly synthetic negative row; no spec requirement was weakened. Second run exited 0. Result: `.f89-evidence/dual-lane-design-verification.json`.
- Edits recorded outside specfolder: `dual-lane-spec-correction.diff`, `dual-lane-spec-self-check.diff`; final hashes in verification JSON are authoritative (earlier hash receipts predate last wording refinement).
- `git diff --check`: exit 0. No command-stub suite ran, so no new binary-integrity claim is needed.

Existing recovery13 functional **5969 passed /18 deselected**, full Black **13 would reformat**, mypy **296 errors in59 files** remain PRE-CORRECTION; static failures UNWAIVED. No fresh functional/static proof, live entitlement, release or complete workflow claim. Next medium implementer follows `dual-lane-correction-handoff-20261010.md`; independent review/assessment remain pending afterward.
