# Latest-main integration verification

Branch: feature-96_chat_transcript. All prior unstaged/untracked implementation
work was committed in d8720c1 before merge. Main 2b2c7dc was reconciled in bb7ba51;
main advanced during verification, so installer update 012bb24 was also merged
in f0f1c5b. A final remote heads query confirmed origin/main remains
012bb24c05a9c4416e2fa827e68801e634913404, already an ancestor of this branch.

## Resolution

Preserved the extracted ChatTranscript and upstream Herdr/session replacement,
workflow visibility and async visualizer lifetimes. Updated upstream tests to
observe their new presentation owner without restoring removed app-owned state.
Retained upstream prepare-before-retire replacement ordering and failed viewer
retry/new truthful notice semantics. Added per-await captured-session replay
cutoffs and updated required task-summary test input. Adopted upstream document
consolidation; extraction-specific architecture is retained in architecture.md.

One precise animation test now records its pre-interruption paint at actual key
dispatch rather than before queuing the key. A later full run exposed a separate
hidden-prepend setup race: PageUp preceded append-layout settlement. The fixture
now waits boundedly for actual follow-pin retirement, bottom geometry and visible
READ-LATER content; all named-row/growth/canonical-byte assertions remain intact.
No production change was made for either test-observation timing repair.

## Actual gates

- Upstream Herdr TUI partition: 353 passed.
- Startup/lifecycle/full-flow targeted run: 203 passed, one obsolete barrier-signature
  failure subsequently corrected for the new captured-owner keyword.
- First full attempt timed out at the 1800-second tool limit; no success inferred.
- Reconciled 2b2c7dc full default gate: 11505 passed, 20 deselected, 857 warnings.
- First 012bb24 full run: 11504 passed, one fixture-setup race (recorded above).
- Focused final scrolling tests: 42 passed.
- **Final latest-main full default pytest: 11505 passed, 20 deselected,
  857 warnings, 1989.31 seconds, exit 0.**

Exact final command (application cwd):

```sh
env -i PATH=/root/.pyenv/versions/slo-harness/bin:/usr/bin:/bin \
 HOME=/tmp/slo-main-merge/home TMPDIR=/tmp/slo-main-merge/tmp \
 VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PYTHONDONTWRITEBYTECODE=1 \
 PYTHONPATH="$PWD" SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" \
 SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 \
 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 \
 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 \
 /root/.pyenv/versions/slo-harness/bin/python -B -m pytest -p no:cacheprovider \
 --basetemp=/tmp/slo-main-merge/pytest-verified -q
```

No additional test paths/markers/exclusions: project default non-E2E selection
applies. Herdr tests opt in through existing isolated fake-process fixtures.
Warnings include dependency deprecations and existing AsyncMock warnings; this is
not a warning-free claim. No static or live-provider/manual-terminal acceptance
is inferred. The final changed test passed Black and diff whitespace checks.

Task-created /tmp/slo-main-merge resources and /tmp/chat-merge-* scratch/log files
are removed after recording this summary. No persistent services launched by the
merge task; unrelated test processes and their resources are not touched. Nothing
pushed. The new source/widget/event-flow diagram is in architecture.md.
