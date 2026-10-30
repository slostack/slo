#!/bin/bash
# Scoped offline test receipt runner; uses the reviewed Makefile fallback only.
set -u
export PYENV_VERSION=slo-harness
if [ "$(make test-env)" != fallback ]; then
  echo 'Test environment changed; review before running.' >&2
  exit 2
fi
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export PYTHONPATH="$PWD"
poetry run pytest -m 'not e2e' "$@"
