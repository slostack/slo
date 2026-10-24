#!/bin/bash
# Assessment-only runner: approved existing interpreter, synthetic fallback, no installs.
set -u
cd /root/Code/slo-94-herdr-integration/slo || exit 1
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PYENV_VERSION=slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONPATH="$PWD"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40
receipts="$PWD/docs/implementation/94-herdr/completion-183-receipts"
label="$1"
shift
{ printf 'cwd=%s\n' "$PWD"; printf 'python='; command -v python; python --version; printf 'test-env='; make test-env; printf 'command: '; printf '%q ' "$@"; printf '\n'; } > "$receipts/$label.command"
"$@" > "$receipts/$label.log" 2>&1
result=$?
printf '%s\n' "$result" > "$receipts/$label.exit"
dpkg -V coreutils > "$receipts/$label.coreutils" 2>&1
integrity=$?
printf '%s\n' "$integrity" > "$receipts/$label.coreutils.exit"
tail -n 8 "$receipts/$label.log"
if [ "$integrity" != 0 ] || [ -s "$receipts/$label.coreutils" ]; then
  printf 'STOP: system integrity anomaly\n'; cat "$receipts/$label.coreutils"; exit 99
fi
exit "$result"
