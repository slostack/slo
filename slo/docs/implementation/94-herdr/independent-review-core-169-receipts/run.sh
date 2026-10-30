#!/bin/bash
# Independent bounded core regression run; no full-suite repetition.
set -u
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PYENV_VERSION=slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
r=docs/implementation/94-herdr/independent-review-core-169-receipts
mapfile -t files < <(find tests/agents/slo_agent/herdr -maxdepth 1 -name 'test_*.py' ! -name 'test_session_*' ! -name 'test_attention_*' | sort)
files+=(tests/agents/slo_agent/test_session_identity.py tests/agents/slo_agent/test_token_format.py tests/agents/slo_agent/orchestrator/test_context_reader.py tests/agents/slo_agent/herdr/test_session_lifetime.py tests/tui/test_herdr_activation_faults.py tests/tui/test_herdr_activation_composed.py)
printf '%q ' poetry run pytest -m 'not e2e' -q "${files[@]}" > "$r/targeted.command"
printf '\n' >> "$r/targeted.command"
poetry run pytest -m 'not e2e' -q "${files[@]}" > "$r/targeted.log" 2>&1
result=$?
printf '%s\n' "$result" > "$r/targeted.exit"
dpkg -V coreutils > "$r/targeted.coreutils"
integrity=$?
printf '%s\n' "$integrity" > "$r/targeted.coreutils.exit"
if [ "$integrity" -ne 0 ] || [ -s "$r/targeted.coreutils" ]; then
  cat "$r/targeted.coreutils"
  exit 99
fi
tail -8 "$r/targeted.log"
exit "$result"
