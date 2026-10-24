# Current CI repair coordination

User explicitly requests concurrent repairs of EVERY failing test, one causal diagnosis at a time within each concern. This is a newly authorized in-session repair of failures from commit 4ab10b02727d433779233cd758e35875b09acd78, not an automatic retry/relaunch of aborted wf-2faf. No detached workflow is running.

## Routing and acceptance

Python 3.11 / pytest / asyncio / Textual. Repository /root/Code/slo-94-herdr-integration, application cwd its slo/ subdirectory; branch feature-94-herdr-integration. Follow CLAUDE.md, AGENTS.md, docs/RESEARCH.md, existing docs/implementation/94-herdr/routing.md with current skills paths. Shared rules: skills/engineering/engineering-routing/SKILL.md, engineering-testing/SKILL.md, engineering-ownership/SKILL.md; coding rules skills/coding/coding-rules/SKILL.md then skills/languages/python/python-conventions/SKILL.md; select Python lifecycle and TUI recipes from skills/INDEX.md as relevant. Read actual rules, not just this summary. Workflow skills/orchestration/workflows/code-test-review.md; Code+Test (parallel independent concerns), independent Review, independent Completion required. Early review inside coding before final gates.

Original specs /root/Code/specifications/projects/slo/specifications/94-slo-tui-redesign/herdr. Preserve prior privacy/ownership/restore acceptance, live acceptance remains explicitly user-deferred, NOT passed. Current scope: all local/CI failures, no skipped assertions or exclusion to manufacture success. Prior committed fixes 4ab10b0 remain intact.

CI exact SHA: MR pipeline2970613678/job17338411077, trace /tmp/herdr-ci-4ab10b0.log. 11failed10490passed1skipped19deselected, suite completed1672.76s. Baseline failures are repair targets, not exclusions.

Read existing environments/tests.env without exposing secrets, source for focused local checks; approved poetry/slo-harness. Force SLO_HERDR_DISABLED=1,SLO_AUTO_VISUALIZE=0,PYTHONPATH=$PWD. Do not modify operator env. Also test CI-default model where relevant. Full gates after fan-in: make test (with junit and captured output), make smoke, make lint, changed-file Black, git diff --check, dpkg -V coreutils. Full suite must run after final production edits; repeat affected verification/review on revisions. No concurrent full suites. No real providers, terminal spawns, user process kills, coreutils changes, broad timeout increases, sleeps masking races, or weakened assertions.

## Ownership

A: tests/cli/test_headless_child_abort.py, src/cli/headless.py if proved necessary; all seven child abort failures. Report ci-repair-headless.md.
B: src/tui/app.py and tests/tui/test_workflow_session_list.py; three observation lifecycle failures and related Herdr initialization/replacement regressions. Report ci-repair-observation.md.
C: tests/integration/test_workflow_progress_tui.py and fleet/progress rendering components excluding src/tui/app.py; twenty-child layout failure; all parameter variants. Report ci-repair-fleet.md. If app.py edit needed, return precise finding for B/next coordinated pass, do not write it.
Workers must not edit each other's files, commit, push, run full suite, or spawn workers. Preserve other workers' uncommitted edits. RED reproduction before corrections; exact cause and tests recorded per failure.

## Todo and accounting

- [x] Three parallel focused Code+Test tasks, then early independent feedback (ER-01–04 corrected in retained A/B/C edits).
- [x] Full integrated suite and static/smoke gates; repair every newly found failure. Recovery dispatch 5 / retry 1/3: 10508 full tests, 296 smoke, lint852, Black17 and integrity gates pass. See ci-repair-integrated-gates.md.
- [ ] Independent final review and completion check.
- [ ] Secret-scan, commit/push to same MR and exact-SHA CI require subsequent authorization: current recovery explicitly forbids commits/pushes. No such action taken.

Historical counts are preserved, not reset: verified184 dispatches through accepted turn6; aborted merge continuation began turn7 with two completed children (historical exact dispatch totals need ledger reconciliation). No automatic abort retry. Both turn and per-turn dispatch limits remain explicitly unlimited. Current continuation is dispatch5, failed-task retry1/3: prior kimi-k3 session9b769697-876a-4ed7-971a-753f851dad55 failed exit1 with429 quota, not aborted; GPT recovery preserved all partial edits and completed Code+Test fan-in. Earlier delta-start0/retries0 was the initial state, not a reset; track separately rather than fabricate historical total. No ad-hoc six-call budget: continuation of required code-test-review. Required review not waived. Prior failed-task retries remain historical, not reset.
