# Source only in the verification subprocess; no development environment.
export PYENV_VERSION=slo-harness VIRTUAL_ENV=/root/.pyenv/versions/slo-harness
export PATH="$VIRTUAL_ENV/bin:$PATH"
export SLO_ENV=test SLO_ROOT_DIR="$PWD" SLO_APP_DIR="$PWD" SLO_APP_NAME=slo SLO_LOG_FORMAT=text SLO_DEFAULT_MODEL_NAME=gpt-5.4 SLO_AUTO_VISUALIZE=0 SLO_HERDR_DISABLED=1 SLO_ANTHROPIC_API_KEY=ci-placeholder-tests-are-fully-mocked COLUMNS=120 LINES=40 PYTHONPATH="$PWD"
R=docs/implementation/94-herdr/t6-offline-final-150-receipts
run_gate() {
    name="$1"; shift
    printf '%s\n' "$*" > "$R/$name.command"
    "$@" > "$R/$name.log" 2>&1
    code=$?
    printf '%s\n' "$code" > "$R/$name.exit"
    tail -8 "$R/$name.log"
    return "$code"
}
