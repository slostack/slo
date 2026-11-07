# Dispatch 15 — independent final-review attempt

## Verdict: REVISE — review incomplete, not accepted

This is an independent Step 2 review attempt, not authorship or early feedback. Concrete defects below block READY. **The complete requested final-review process was not completed in this dispatch.** In particular, the whole implementation/test diff, all detailed reports, required recipes and post-hook hard-rule checklist have not been exhaustively reviewed. Do not treat this report as a complete audit or advance to independent completion. No feature-completion claim is made.

Scope: only original `96-agent-message-queue/revised/01-durable-composer/`, checkout `/root/Code/slo-message-queue/slo`, verified branch `message-queue`. Turn1 started1/completed0/partial1; dispatch15/20; zero retries; max60turns. Requested reviewer gpt-6-astra/medium; runtime model identity is not independently attested. No implementation changes, agents, workflow launches, Git publication, packages or host changes. User SLO/docs preserved. Only this report written.

## Blocking findings (finite repair list)

### FR-01 — closed adapter delivery violates required error precedence

**Source/rule:** original DC02 §2.3: unsupported inputs raise TypeError; closed delivery raises RuntimeError, **closed wins**; §5.8 and A9 lifecycle contract.

**Where:** `src/tui/components/prompt_input/adapters/message_submission.py:89–93`.

**Defect:** `handle` checks input type before checking `_closed`. Calling `handle(event=object())` on an adapter closed through its public `close()` raises `TypeError("Unsupported submission input")`, not the specified closed-delivery RuntimeError. This is an observable interface-contract violation, not a style preference. The existing test `tests/tui/test_durable_composer.py:816–840` tests unsupported-open and supported-closed separately, missing their interaction.

**Independent evidence:** safe, in-memory `python -B` probe constructed the real adapter with injected client/receiver, awaited `close()`, then delivered `object()`: `closed unsupported delivery: TypeError Unsupported submission input`; exit0 (exception deliberately captured). No session, database, provider or filesystem write was needed.

**Repair/closure:** enforce closed-wins validation while preserving required loop-affinity behavior. Add a public-lifecycle regression for unsupported delivery after close and retain supported/open/foreign-loop cases. Do not reopen the adapter by mutating private flags to establish those states.

### FR-02 — wait-task bookkeeping grows without bound, even after reset/close

**Source/rule:** DC02 bounded adapter ownership (§3, §5.8); engineering ownership/resource lifetime and bounded operation obligations. This is a concrete resource defect introduced while repairing EF-02, not a demand to discard failures unobserved.

**Where:** `src/tui/components/prompt_input/adapters/message_submission.py:127–133`, `reset`, `_close_owned`, `_join_wait_tasks` (approximately lines190–259).

**Defect:** every started wait is added to `_tasks`, and no path removes an observed completed task. Each new submission scans every historical task to count live waits. Reset observes them but retains them; close also leaves the set populated. A long-lived prompt binding accumulates one Task per submission/retry; failed tasks can additionally retain exception tracebacks and their referenced objects. Work per new admission grows with lifetime submissions, not the four-wait budget.

**Independent evidence:** real adapter, injected immediate-offline client and inert receiver; 100 sequential distinct drafts with an event-loop yield after each produced `100 tracked; 0 live`. Public `reset()` left100 tracked; public `close()` also left100 tracked. Probe exit0. `_drafts_by_id` remained separately capped by its existing eviction logic; that does not bound `_tasks`.

**Repair/closure:** observe completed results and retire their Task references, preserving a bounded failure-reporting mechanism and the EF-02 guarantee that all outstanding siblings are joined before failures propagate. Preserve shared concurrent close and repeated-cancellation behavior. Add a repeated-submission/reset test proving bookkeeping does not scale with all historical calls, together with the existing failing-receiver/held-sibling tests. Do not restore the old silent-discard bug.

### FR-03 — composer lifecycle evidence replaces a private dependency instead of using the specified binding seam

**Source/rule:** DC02 §8 explicitly injects ScriptedMessagingClient through `replace_submission_binding` (no patching); `coding/test-verification-policy` prohibits swapping internal collaborators through private attributes and requires constructor/factory/parameter injection. Python hard-rule checklist §1.5 applies.

**Where:** `tests/tui/test_durable_composer.py:740–753`, `_rebind_scripted_client`; callers include lifecycle and failure cases in that file. Lines833–840 also reopen a publicly closed adapter by assigning `_closed` and `_closing_task`.

**Defect:** the helper claims “nothing is patched” but directly assigns `adapter._client = client`. It bypasses the implemented component replacement/retirement path and can hide lifecycle ordering failures. The comment says DC04 owns replacement as though it were still future work; DC04 is now part of this final-review scope. Publicly closed adapter state is separately fabricated for the foreign-loop probe.

**Repair/closure:** use the real public binding replacement interface for mounted component tests, and `MessageSubmissionAdapter.register(client=..., receiver=...)` for isolated adapter-contract tests. Construct separate legitimate adapter lifetimes for closed and foreign-loop tests rather than reopening private state. Preserve every existing outcome/cancellation/sibling/error assertion; rerun affected tests. Audit this helper's callers as one bounded repair, not unrelated historical tests across the repository.

## Requirement/evidence map — review coverage, NOT acceptance

All nine original §8 A-row tables were read. The following covers every original ID range but explicitly marks the limits of this attempt. Author evidence locations are navigation references, not independent verification. No row is classified accepted solely from test totals.

| Original requirements | Author evidence pointers | Independent disposition this dispatch |
|---|---|---|
| DC01.A1–A8 | continuation-ledger dispatch4; injected activation/durable composer tests; dispatch12/14 | A-row contracts read; full entry→startup→provider→shutdown verification unfinished. |
| DC02.A1–A12 | durable composer/prerequisites/protocol/adapter registration tests; dispatch12 | Submission adapter fully read; relevant lifecycle test/helper sections read; FR-01–03 block A9/lifecycle evidence and bounded adapter contract. Complete ordering/capacity/eager/typing matrix not independently reconciled. |
| DC03.A1–A11 | dispatch5-dc03; observation/transcript identity/history tests | Contracts read; identity/hash/recall/compaction/overflow/presentation implementation and assertions not fully reviewed. |
| DC04.A1–A8 | dispatch6-dc04; composer retirement tests | Contracts read; adapter shared-close/join correction inspected, but component/app handoff, acknowledgement and cancellation closure unfinished. |
| DC05.A1–A9 | dispatch7-dc05; retained recovery/messages/store tests | Contracts read; consent/security/expiry/atomic recovery review unfinished. |
| DC06.A1–A7 | dispatch8-dc06; messaging session control tests | Contracts read; real abort/clear/new/lifecycle trace unfinished. |
| DC07.A1–A11 | dispatch9-dc07; dispatch12 complementary A4/A8 rationale; finite/headless/steer tests | Queue finite-cutoff and HeadlessRunner diffs read. Rationale read, but actual assertions and complete stop/reconciliation owner trace not reconciled. **No acceptance of complementary A4/A8 evidence yet.** |
| DC08.A1–A11 and §5.6 | dispatch10-dc08; dispatch12; legacy admission/bridge/displacement tests | Queue saved-target verification diff read; bounded scan/digest/ack/security and actual displacement assertions not fully reviewed. |
| DC09.A1–A6 | dispatch11-dc09; dispatch12/14; visual/failure/default composition tests | Original matrix acceptance rows read. Host-scoped supported_priorities diff and dispatch12 rationale inspected: generic default preserves normal+urgent, host restriction is separate. Complete host wiring, full visual/failure cells, rollback and no-regression assertions remain unverified by this reviewer. Full test receipt is corroborated below. |

### Earlier findings EF-01–05

`early-review.md` read in full; current handoff/ledger closure claims read. EF-02's shared close, reference release and sibling join changes are present in the actual adapter. FR-02 identifies a residual bookkeeping defect in that repair. EF-01 exact mounted/provider assertions, EF-03 component retirement, EF-04 app-owned shutdown and EF-05 shared recall identity need complete source/assertion reconciliation; this attempt does not independently close them.

### Dispatch14 boundary changes

Read dispatch14 report in full and ownership.py diff. Opening existing directory ancestors before trying mkdir preserves no-follow intent and avoids unnecessary attempted mutation. Headless diff was inspected. Credential/backend refusal, pause/retain-before-wake, terminal redaction and restored no-echo oracle were read as author explanations, **not fully traced in sessions/service.py or the changed regression assertions**. No claim that assertion weakening/off-scope regression has been exhaustively ruled out.

## Gate evidence and commands

No full-suite rerun was necessary to establish the receipt contents. No pytest run was performed in this attempt.

- Read `logs/dispatch14-full-test.log` header and final summary plus `.exit`: Python3.11.7, pytest9.0.3, six workers/12265items; **12265passed,1266warnings,527.56s; exit0**. Consistent with reported `make test PYTEST_WORKERS=6`.
- Read separate `logs/dispatch14-collection.log` tail and `.exit`: **12265/12286 collected,21deselected,exit0**. These are collection exclusions, not skipped executed tests.
- Read lint/Black exit receipts: each0. Their complete output/path inventory and relation to current file content were not exhaustively verified. Do not promote this to an independent static-gate audit.
- Attempted `dispatch14-integrity.exit` read found no file with that aggregate name; the report may use per-command receipt names. This is **not** evidence of failed integrity checks; receipt lookup remains unfinished.
- Read-only inventory: `git status --short`, `git diff --stat`, `git branch --show-current`, selected `git diff -- <paths>`, source/spec/report/skill/KB reads via cat/sed/nl/grep/tail. Untracked adapter implementation was explicitly read; untracked tests were inspected selectively, not ignored or claimed fully reviewed.
- Two in-memory probes used `python -B` with `VIRTUAL_ENV=/root/.pyenv/versions/slo-harness`, matching PATH prefix and routing synthetic environment (`SLO_ENV=test`, root/app=current checkout, model gpt-5.4, visualization off, Herdr disabled, synthetic Anthropic placeholder,120×40,PYTHONPATH=current checkout). They imported the real adapter and used injected minimal clients/receivers; no file-store/session/provider use. LangGraph deprecation warning was printed. Results are detailed in FR-01/02.

No approved baseline exceptions exist. Receipt success does not excuse missing required behavior or review evidence.

## Process limitations and next action

Read the exact installed Code-Test-Review workflow, full review-feature-code and full Python code-review-rules checklist; shared routing/review/testing/ownership; Python root; current routing/handoff/ledger, dispatch12/14 and early review. Some combined source/skill reads truncated; they cannot be counted as full reads. README was only partially read; full required project/KB and selected recipe loading remains incomplete. This report deliberately does not assert completion of Steps1–8 or the mandatory post-hook hard pass.

The actual limitation is incomplete review execution and source/assertion coverage, not an unavailable test environment, a claimed elapsed60–90minute limit, or a failed full gate. Do not fabricate a workflow budget conflict: six dispatches remain after dispatch14 and this review consumes dispatch15. No review loop has completed.

Next: return FR-01–03 to Step1 for bounded repair and verification, then complete independent final review of the entire original scope (including still-unreviewed requirements above and all mandatory hard rules). Reuse valid unchanged receipts; recheck changed boundaries and run required gates on the repaired source. Only after an accepted final review may the separate independent completion check proceed.

### Checklist

- Must-fix code: FR-01 closed-wins; FR-02 observed bounded task lifetime.
- Required tests: FR-01 interaction, FR-02 bounded history plus failure/cancellation preservation, FR-03 genuine public injection/lifetimes.
- Product/spec decisions: none invented; no urgency/IPC/channel expansion requested.
- Review/documentation: complete remaining source/requirement/assertion/hard-rule audit; preserve user documents. No optional nonblocking recommendations issued in this partial review.
