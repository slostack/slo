# Core161 independent execution receipts

CWD `/root/Code/slo-94-herdr-integration/slo`. No product/test/specification edits. Review probes are inline Python, not installed code. All probe state uses `TemporaryDirectory(prefix='herdr-core161-')`, with resolved containment assertions before file writes. No external executable, provider, real Herdr, terminal window or system-linked fixture.

Environment for targeted tests:
```bash
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
```
Verified `command -v python` → `/root/.pyenv/versions/slo-harness/bin/python`; `python --version` → Python 3.11.7; `make test-env` → fallback. No environment file sourced or secrets read.

`targeted.command`, `targeted.log`, `targeted.exit`, `targeted.coreutils` record the existing owned-test selection. Root conftest/state_isolation fully read before execution; independent fake-only capability and terminal guards retained.

`probes.md` contains the exact deterministic probe code and observed outputs. Initial probes ran before this receipt was written; a retained rerun follows. No pytest failing regression files are added by this review. These scripts assert defect reproduction, not desired behavior: exit zero means the defect was reproduced.

`manifest.log` records verification of all 835 frozen160 inputs, and exact differences from156's 844-input scope. Ten156-only entries remain files; one new160 entry is the permanent usage trace test. Count change is not deletion evidence.

After every executed probe/test batch, `dpkg -V coreutils` is checked. Silent output is required; any anomaly stops work. Full suite is not redundantly rerun: unchanged frozen160 retained full8680/smoke288/lint806 receipts are inspected, not treated as independent correctness proof.
