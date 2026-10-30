# Independent dispatch155 commands and results

Cwd: `/root/Code/slo-94-herdr-integration/slo`.

Read-only identity verified before writes: repository root `/root/Code/slo-94-herdr-integration`, branch `feature-94-herdr-integration`, origin `https://gitlab.com/core-27/slo.git`, HEAD/base `d0e3a756689f2675e5507034d43cd8b272d3c6b8`.

Both pytest invocations explicitly exported:

```sh
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness PYENV_VERSION=slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
```

`python --version`: Python 3.11.7. `make test-env`: fallback. No environment file sourced. Root fixtures were read before execution. The receipt-local probe explicitly loads `tests.conftest` to retain pre-import isolation and registered fake-only transport admission outside normal test discovery.

```sh
poetry run pytest -p tests.conftest -m 'not e2e' docs/implementation/94-herdr/independent-review-155-receipts/test_profile_probe.py
```

`profile.log` / `profile.exit`: **1 failed, 2 warnings, 2.08s**, exit 1. Real session publication with captured detail config has no reasoning token. This is intended-behavior RED, not a setup error. Cleanup completes in finally.

```sh
poetry run pytest -m 'not e2e' tests/agents/slo_agent/herdr/test_projection.py tests/agents/slo_agent/herdr/test_gate_diagnostics.py tests/agents/slo_agent/test_agent_usage_commit_regressions.py tests/integration/test_herdr_full_flow.py::test_pilot_configuration_and_typed_viewer_journey
```

`targeted.log` / `targeted.exit`: **80 passed, 34 warnings, 24.22s**, exit 0. This includes all four existing typed-viewer journey cases. Counts are not added to the prior full gate.

After each invocation `/usr/bin/dpkg -V coreutils` was silent, exit 0: `coreutils*.log/.exit`.

```sh
sha256sum -c docs/implementation/94-herdr/integrated-gates-154-receipts/source-before.sha256
```

All 843 lines OK, exit 0, recorded in `manifest-check.log/.exit` after independent tests. Manifest digest `d75444038d2e52cbbb4511cb6312ac9b69e5b5d27d96d2643d981b29e5dc4313`. Review-only files are additional inputs, not falsely included in the prior freeze.

A stdlib tomllib comparison of `git show d0e3a756:slo/poetry.lock` against current poetry.lock independently found all 87 prior package dictionaries identical, no removed packages, only types-pyyaml added. No installation or runtime-distribution audit performed here.

Read retained dispatch154 full/smoke/lint exit files (all 0) and actual log summaries: full8667/19 deselected/777 warnings; smoke288/2 warnings; lint804 clean. These are prior execution receipts, not independent reruns. Other gate summaries remain author claims pending full receipt reconciliation.

Inventory commands: `git diff --relative --name-status d0e3a756` and `git ls-files --others --exclude-standard src tests`; outputs retained separately. Neither inventory nor hash verification is a semantic read claim.
