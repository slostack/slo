# Independent review158 execution receipts

Cwd: `/root/Code/slo-94-herdr-integration/slo`.
Initial read-only Git inspection: expected `feature-94-herdr-integration`, origin
`https://gitlab.com/core-27/slo.git`, HEAD/base
`d0e3a756689f2675e5507034d43cd8b272d3c6b8`. No Git mutation.

Every pytest invocation used this subprocess-only environment; no secrets file sourced:

```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH=/root/.pyenv/versions/slo-harness/bin:$PATH
export PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo
export SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4
export SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1
export SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked
export COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
```

`which python` returned `/root/.pyenv/versions/slo-harness/bin/python`;
`python --version`: Python3.11.7; `make test-env`: fallback.

## Commands/results

1. `python -m pytest -p tests.conftest docs/implementation/94-herdr/independent-review-158-receipts/test_usage_trace_probe.py docs/implementation/94-herdr/independent-review-155-receipts/test_profile_probe.py -q`
   - `probes.log/.exit`: 1 failed,1 passed,3 warnings; exit1. At this point the new probe file contained only the direct-agent test. Original155 profile probe passes unchanged.
2. `python -m pytest -p tests.conftest docs/implementation/94-herdr/independent-review-158-receipts/test_usage_trace_probe.py -q`
   - `usage.log/.exit`: 2 failed,4 warnings; exit1. Added actual session/real append test initially raised cancellation in the appended-message callback.
3. Same command after replacing direct cancellation injection in the session case with a barrier followed by external `task.cancel()`:
   - `usage-real-cancel.log/.exit`: 2 failed,4 warnings; exit1. Final probe file retains this stronger version. Real history contains assistant_message and run_aborted, but session total is None rather than3.
4. `python -m pytest -q tests/agents/slo_agent/herdr/test_session_metadata_profile.py tests/agents/slo_agent/test_agent_usage_commit_regressions.py tests/agents/slo_agent/herdr/test_session_publication_compositions.py tests/cli/test_headless_parity.py`
   - `targeted.log/.exit`: 70 passed,24 warnings; exit0.

`dpkg -V coreutils` was silent after each invocation. First check was inline;
subsequent `coreutils*.log` files are empty and corresponding exits0.
Only the new review probe was Black-formatted. No product/test-suite file changed.

## Retained evidence independently checked

`sha256sum --check --quiet ../profile-revision-156-receipts/source-after.sha256`
(run with the full cwd-relative path) exit0, including after independent tests.
Before/after each have844 entries and identical manifest SHA256:
`375a9c4ab0b6550e9067b813dcf09fc988cebe3d4b83c218af72b4fb79a44e0f`.
`manifest-check.log/.exit` retains the last check.

Actual command/exit and terminal log lines inspected for156 full8675/19 deselected,
smoke288, lint805, B1460, C1467, D1677, surrounding472, Black216. These are retained
runs, not independently rerun full gates. Green receipts do not cover the newly
exposed cancellation boundary.

Memory-only TOML comparison against `git show HEAD:./poetry.lock`: all87 existing
package dictionaries unchanged, zero removed; only types-pyyaml added. No package
installation or installed-distribution audit performed. Executor production file
has zero base diff. `git diff --check` silent.

Inventory files enumerate tracked modifications and untracked src/tests.
`base-source-test.diff` and `static-test.diff` are captured diffs, not certifications
that every line was read. See report's explicit read limits.
