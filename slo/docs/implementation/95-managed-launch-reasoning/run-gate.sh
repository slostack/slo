#!/bin/bash
# Command-local approved environment; retain exact command, output and status.
set -u
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
export PYTHONPATH="$PWD"
name=$1
shift
root=docs/implementation/95-managed-launch-reasoning
printf 'cwd=%s\n' "$PWD" > "$root/$name.command"
printf '%q ' "$@" >> "$root/$name.command"
printf '\nEnvironment: run-gate.sh command-local exports\n' >> "$root/$name.command"
"$@" > "$root/$name.log" 2>&1
result=$?
printf '%s\n' "$result" > "$root/$name.exit"
tail -70 "$root/$name.log"
exit "$result"
