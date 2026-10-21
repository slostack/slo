#!/bin/bash
# Scoped offline test runner; no environment file is sourced.
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
label=$1
shift
mkdir -p docs/implementation/94-herdr/core-contracts-165
python -m pytest -q "$@" >"docs/implementation/94-herdr/core-contracts-165/$label.log" 2>&1
result=$?
printf '%s\n' "$result" >"docs/implementation/94-herdr/core-contracts-165/$label.exit"
dpkg -V coreutils >"docs/implementation/94-herdr/core-contracts-165/$label.coreutils"
cat "docs/implementation/94-herdr/core-contracts-165/$label.coreutils"
tail -15 "docs/implementation/94-herdr/core-contracts-165/$label.log"
exit "$result"
