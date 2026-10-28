#!/bin/bash
# Independent bounded review: approved interpreter, tracked synthetic fallback only.
export VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH" PYENV_VERSION=slo-harness
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
root=docs/implementation/94-herdr/review-wiring-178-receipts
label=$1
shift
printf '%q ' "$@" > "$root/$label.command"
printf '\n' >> "$root/$label.command"
"$@" > "$root/$label.log" 2>&1
status=$?
printf '%s\n' "$status" > "$root/$label.exit"
dpkg -V coreutils > "$root/$label.coreutils" 2>&1
integrity=$?
printf '%s\n' "$integrity" > "$root/$label.coreutils.exit"
tail -35 "$root/$label.log"
printf 'exit=%s coreutils_exit=%s\n' "$status" "$integrity"
if [ "$integrity" -ne 0 ] || [ -s "$root/$label.coreutils" ]; then
    cat "$root/$label.coreutils"
    exit 99
fi
exit "$status"
