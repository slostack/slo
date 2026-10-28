#!/bin/bash
set -o pipefail
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 SLO_HERDR_DISABLED=1
export PYTHONPATH="$PWD"
poetry run pytest -q -m 'not e2e' tests/agents/slo_agent/herdr/test_daos.py tests/agents/slo_agent/herdr/test_projection.py "$@"
