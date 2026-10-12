#!/usr/bin/env bash
# install.sh — one-line installer for slo.
#
#   curl -fsSL <url>/install.sh | bash
#
# Installs slo as a normal pipx application straight from its git repository.
# pipx builds the package in its own isolated venv and puts the `slo` binary on
# your PATH. SLO_HOME (~/.slo) is slo's *runtime data* (sessions, logs,
# credentials), NOT a code checkout — the old installer cloned the repo into
# ~/.slo, which collides with that data and aborts ("destination path already
# exists") on any machine where slo has run. After a successful pipx install,
# the ONLY writes under SLO_HOME are the non-secret managed environment file
# ~/.slo/shell/environment.sh (default SLO_HOME, SLO_SKILLS_DIR, SLO_KB_DIR) and bounded
# source blocks in shell startup files (spec 80); sessions, credentials, user
# skills, user workflows, and any legacy ~/.slo/skills tree are never touched.
#
# On a bare machine this first provisions the toolchain pipx needs. macOS uses
# Homebrew for pyenv, git, and pipx. Debian-family Linux uses apt for git,
# pyenv's build headers, and pipx, then git-clones pyenv itself before building
# the pinned Python (3.11.x). Every step is a no-op when already satisfied, so
# re-running upgrades slo in place. No interactive prompts.
#
# Configuration (all overridable from the environment):
#   SLO_VERSION        version to install (default: pinned release baked in at
#                      publish time). Pass "dev" to track the main branch.
#   SLO_REPO_URL       git URL to install from (default below)
#   SLO_REPO_FALLBACK_URL mirror used when the primary is inaccessible; empty disables
#   SLO_PYTHON_VERSION pinned interpreter version (default: 3.11.7)
#
# Testability: every function below is sourceable. The `main` dispatch at the
# bottom runs only when the script is executed directly, not when sourced — so
# the unit tests in tests/cli/test_install.py can source this file and exercise
# each function against a stubbed PATH without mutating the host.
set -euo pipefail

# ---- Configuration (single source of truth) --------------------------------
SLO_REPO_URL="${SLO_REPO_URL:-https://gitlab.com/core-27/slo.git}"
# Do not silently replace a custom repository with the official Slo mirror.
if [ "$SLO_REPO_URL" = "https://gitlab.com/core-27/slo.git" ]; then
    SLO_REPO_FALLBACK_URL="${SLO_REPO_FALLBACK_URL-https://github.com/slostack/slo.git}"
else
    SLO_REPO_FALLBACK_URL="${SLO_REPO_FALLBACK_URL-}"
fi
SLO_REF="${SLO_REF:-main}"
SLO_PYTHON_VERSION="${SLO_PYTHON_VERSION:-3.11.7}"

# ---- Version selection ------------------------------------------------------
# SLO_VERSION controls the git ref to install:
#   unset / empty → use SLO_REF (default pinned at publish time by deploy script)
#   "dev"         → main branch
#   anything else → treated as a release tag or branch name
if [ "${SLO_VERSION:-}" = "dev" ]; then
    SLO_REF="main"
elif [ -n "${SLO_VERSION:-}" ]; then
    SLO_REF="$SLO_VERSION"
fi

# ---- apt behaviour (Linux) -------------------------------------------------
# Exported once so no apt-get step below can block on an interactive prompt.
# Meaningless on macOS; harmless there.
export DEBIAN_FRONTEND=noninteractive

# Path to the freedesktop os-release file used for Linux distro detection.
# Overridable so the unit tests can point it at a temp file instead of the host's.
SLO_OS_RELEASE_FILE="${SLO_OS_RELEASE_FILE:-/etc/os-release}"

# ---- Small helpers ---------------------------------------------------------
slo_log() {
    # Emit a progress line to stderr so stdout stays reserved for any future
    # machine-readable output.
    echo "→ $*" >&2
}

slo_has() {
    # Return success when an executable named "$1" is resolvable on PATH.
    command -v "$1" >/dev/null 2>&1
}

slo_sudo() {
    # Echo "sudo" when we are not already root and sudo is available; echo
    # nothing when we are root (or sudo is unavailable).
    if [ "${EUID:-1}" = "0" ]; then
        return 0
    fi
    if slo_has sudo; then
        echo "sudo"
    fi
}

slo_apt_get() {
    # Run apt-get, escalating with sudo only when needed.
    local sudo_bin=""
    sudo_bin="$(slo_sudo)"
    if [ -n "$sudo_bin" ]; then
        "$sudo_bin" apt-get "$@"
        return 0
    fi
    apt-get "$@"
}

slo_apt_refresh() {
    # Refresh the apt package index at most once per installer run.
    if [ -n "${_SLO_APT_REFRESHED:-}" ]; then
        return 0
    fi
    slo_log "refreshing apt package index"
    slo_apt_get update
    _SLO_APT_REFRESHED=1
}

slo_apt_install() {
    # Refresh the index once, then install the named apt packages.
    slo_apt_refresh
    slo_log "installing apt packages: $*"
    slo_apt_get install -y "$@"
}

slo_os_kind() {
    # Echo a normalized OS token: "macos", "linux", or "unsupported".
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux) echo "linux" ;;
        *) echo "unsupported" ;;
    esac
}

slo_linux_distro() {
    # Echo a normalized Linux distro-family token: "debian" for Debian,
    # Ubuntu, and apt-based derivatives (via ID / ID_LIKE), else "unsupported".
    # Parses os-release with bash builtins only so the unit tests' stubbed PATH
    # remains sufficient.
    local os_release="${SLO_OS_RELEASE_FILE:-/etc/os-release}"
    local id=""
    local id_like=""
    local key=""
    local value=""

    if [ -r "$os_release" ]; then
        while IFS='=' read -r key value; do
            value="${value%\"}"
            value="${value#\"}"
            case "$key" in
                ID) id="$value" ;;
                ID_LIKE) id_like="$value" ;;
            esac
        done < "$os_release"
    fi

    case "$id" in
        ubuntu | debian)
            echo "debian"
            return 0
            ;;
    esac

    case " $id_like " in
        *" ubuntu "* | *" debian "*)
            echo "debian"
            return 0
            ;;
    esac

    echo "unsupported"
}

# ---- 1. Homebrew (macOS toolchain provider) --------------------------------
slo_ensure_brew() {
    # Homebrew is the macOS toolchain provider. On Linux we use the native
    # package manager instead, so this is a no-op there.
    if [ "$(slo_os_kind)" != "macos" ]; then
        return 0
    fi
    if slo_has brew; then
        slo_log "brew present"
        return 0
    fi
    slo_log "installing Homebrew (non-interactive)"
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    slo_activate_brew
}

slo_activate_brew() {
    # Evaluate `brew shellenv` from the first Homebrew prefix that exists so brew
    # and its installed shims are usable later in this same script invocation.
    local prefix
    for prefix in /opt/homebrew /usr/local /home/linuxbrew/.linuxbrew; do
        if [ -x "$prefix/bin/brew" ]; then
            eval "$("$prefix/bin/brew" shellenv)"
            return 0
        fi
    done
}

# ---- 2. pipx (OS-aware) ----------------------------------------------------
slo_ensure_pipx() {
    # Install pipx when absent, using the platform-standard mechanism. No-op when
    # pipx already resolves. Always finishes with pipx ensurepath (best effort).
    if slo_has pipx; then
        slo_log "pipx present"
        return 0
    fi
    local os
    os="$(slo_os_kind)"
    slo_log "installing pipx for $os"
    if [ "$os" = "macos" ]; then
        brew install pipx
    elif [ "$os" = "linux" ] && [ "$(slo_linux_distro)" = "debian" ]; then
        slo_install_pipx_debian
    else
        python3 -m pip install --user pipx
    fi
    # A pip --user fallback drops pipx into the Python user-base bin (~/.local/bin),
    # which is not yet on PATH for this running process. Prepend it so pipx resolves
    # for the rest of this run (ensurepath and the pipx install in slo_install).
    # Harmless on the brew / apt-pipx paths where pipx is already resolvable.
    export PATH="$(python3 -m site --user-base 2>/dev/null)/bin:$PATH"
    pipx ensurepath || true
}

slo_install_pipx_debian() {
    # Prefer the distro's pipx package on Debian-family Linux. When apt has no
    # pipx package (older Ubuntu / Debian), fall back to a user pip install.
    if slo_apt_install pipx; then
        return 0
    fi
    slo_log "apt has no pipx package; falling back to pip --user"
    slo_apt_install python3-pip python3-venv
    python3 -m pip install --user pipx
}

# ---- 3. pyenv --------------------------------------------------------------
slo_ensure_pyenv() {
    # Ensure pyenv exists, then initialize it so subsequent `pyenv install` /
    # shim lookups work within this script.
    if slo_has pyenv; then
        slo_log "pyenv present"
        slo_activate_pyenv
        return 0
    fi

    if [ "$(slo_os_kind)" = "macos" ]; then
        slo_log "installing pyenv via brew"
        brew install pyenv
    else
        export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
        if [ ! -d "$PYENV_ROOT" ]; then
            slo_log "installing pyenv via git clone into $PYENV_ROOT"
            git clone --depth 1 https://github.com/pyenv/pyenv.git "$PYENV_ROOT"
        else
            slo_log "pyenv checkout already present at $PYENV_ROOT"
        fi
    fi

    slo_activate_pyenv
}

slo_activate_pyenv() {
    # Put pyenv's bin + shims on PATH and run `pyenv init` for this shell so the
    # pinned interpreter is resolvable as `python3.11` after installation.
    export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
    export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
    if slo_has pyenv; then
        eval "$(pyenv init - 2>/dev/null)" || true
    fi
}

# ---- 4. Pinned Python via pyenv --------------------------------------------
slo_ensure_python() {
    # Install the pinned Python version via pyenv (-s skips when already present)
    # and rehash shims so `python3.11` resolves.
    slo_log "ensuring Python $SLO_PYTHON_VERSION via pyenv"
    pyenv install -s "$SLO_PYTHON_VERSION"
    pyenv rehash || true
}

# ---- 5. SLO_HOME (runtime data dir — created, never used as a checkout) -----
slo_ensure_home() {
    # Honour an existing SLO_HOME; otherwise default to ~/.slo. This is slo's
    # runtime data directory (sessions, logs, credentials). We only ensure it
    # exists so first run has a home — the install itself writes nothing here.
    # Echoes the resolved path.
    if [ -z "${SLO_HOME:-}" ]; then
        SLO_HOME="$HOME/.slo"
        slo_log "SLO_HOME unset; defaulting to $SLO_HOME"
    else
        slo_log "SLO_HOME=$SLO_HOME (from environment)"
    fi
    mkdir -p "$SLO_HOME"
    export SLO_HOME
    echo "$SLO_HOME"
}

# ---- git (required for pip's git+ VCS fetch and Linux pyenv clone) ---------
slo_ensure_git() {
    # git is mandatory for the VCS install. Install via brew on macOS and via
    # apt on Debian/Ubuntu; on any other platform, error with guidance rather
    # than guess a package manager.
    if slo_has git; then
        slo_log "git present"
        return 0
    fi
    local os
    os="$(slo_os_kind)"
    slo_log "installing git for $os"
    if [ "$os" = "macos" ]; then
        brew install git
        return 0
    fi
    if [ "$os" = "linux" ] && [ "$(slo_linux_distro)" = "debian" ]; then
        slo_apt_install git
        return 0
    fi
    echo "error: git not found and no supported package manager detected (need brew on macOS or apt on Debian/Ubuntu). Install git and re-run." >&2
    exit 1
}

# ---- 5b. Linux build dependencies for pyenv --------------------------------
slo_ensure_build_deps() {
    # Install the headers pyenv needs to compile CPython on Linux. No-op on
    # macOS; on non-Debian Linux, log guidance and continue.
    if [ "$(slo_os_kind)" != "linux" ]; then
        return 0
    fi
    if [ "$(slo_linux_distro)" != "debian" ]; then
        slo_log "non-Debian Linux: skipping apt build-deps; ensure pyenv build prerequisites yourself"
        return 0
    fi
    slo_log "installing pyenv build dependencies via apt"
    slo_apt_install \
        make build-essential libssl-dev zlib1g-dev libbz2-dev \
        libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
        xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
        ca-certificates git
}

# ---- 6. Install via pipx straight from the repo ----------------------------
slo_pipx_spec() {
    # Echo the pip VCS requirement pipx installs from:
    #   git+<url>@<ref>#subdirectory=<subdir>
    # The Python project lives in the repo's `slo/` subdirectory, not the repo
    # root, so pip must be told where pyproject.toml is via #subdirectory. Set
    # SLO_REPO_SUBDIR to override; set it to empty for a root-level project.
    # The repository is public. Keep the URL exactly as configured so this
    # installer never reads, embeds, or writes repository credentials.
    local url="${1:-$SLO_REPO_URL}"
    local subdir="${SLO_REPO_SUBDIR-slo}"
    local frag=""
    [ -n "$subdir" ] && frag="#subdirectory=${subdir}"
    echo "git+${url}@${SLO_REF}${frag}"
}

slo_python_bin() {
    # Resolve the concrete pinned interpreter to hand pipx. The bare `python3.11`
    # pyenv shim only resolves when SLO_PYTHON_VERSION is the *active* pyenv
    # version — which it usually is NOT on a multi-version machine (the active
    # version is whatever virtualenv the shell is in), so the shim aborts with
    # "command not found". Prefer the real binary under pyenv's versions dir;
    # fall back to a PATH python only when that is unavailable.
    local root="" bin=""
    if slo_has pyenv; then
        root="$(pyenv root 2>/dev/null || true)"
    fi
    bin="${root:+$root/versions/${SLO_PYTHON_VERSION}/bin/python3.11}"
    if [ -n "$bin" ] && [ -x "$bin" ]; then
        echo "$bin"
    elif slo_has python3.11; then
        echo "python3.11"
    else
        echo "python3"
    fi
}

slo_install() {
    # Install slo as an isolated pipx application straight from the repo: no
    # clone, no editable checkout, nothing written to SLO_HOME. --force makes
    # re-runs upgrade in place.
    #
    # Because nothing is written to SLO_HOME, skills/ cannot be found on disk
    # after install — it must travel inside the wheel. That is what
    # `[tool.poetry] include` in pyproject.toml is for; dropping it leaves the
    # installed agent running with zero vendored skills. Guarded by
    # tests/cli/test_wheel_contents.py.
    #
    # pipx auto-selects a uv backend whenever any `uv` is on PATH but never
    # checks that it runs; a stale pyenv `uv` shim (uv present only in some
    # virtualenvs) then aborts the install. Fall back to pip when uv is present
    # but not runnable, unless the caller already pinned a backend.
    if [ -z "${PIPX_DEFAULT_BACKEND:-}" ] && slo_has uv && ! uv --version >/dev/null 2>&1; then
        slo_log "uv on PATH is not runnable; forcing pipx pip backend"
        export PIPX_DEFAULT_BACKEND=pip
    fi
    local spec python_bin status
    spec="$(slo_pipx_spec)"
    python_bin="$(slo_python_bin)"
    # Credentials stay with Git's existing helpers; never embed setup tokens.
    export GIT_TERMINAL_PROMPT=0
    export GIT_HTTP_LOW_SPEED_LIMIT="${GIT_HTTP_LOW_SPEED_LIMIT:-1}"
    export GIT_HTTP_LOW_SPEED_TIME="${GIT_HTTP_LOW_SPEED_TIME:-30}"
    slo_log "installing slo via pipx (python: $python_bin) from the primary repository at ${SLO_REF}"
    if pipx install --force --python "$python_bin" "$spec"; then
        return 0
    else
        status=$?
    fi
    # A missing executable, custom source, or explicit opt-out is not an outage.
    if [ "$status" = "127" ] || [ -z "$SLO_REPO_FALLBACK_URL" ] || [ "$SLO_REPO_FALLBACK_URL" = "$SLO_REPO_URL" ]; then
        return "$status"
    fi
    if slo_remote_available "$SLO_REPO_URL" "$python_bin"; then
        # GitLab can be reached: preserve build/dependency/missing-ref errors.
        return "$status"
    fi
    slo_log "primary repository inaccessible; trying the mirror at the same ref (${SLO_REF})"
    spec="$(slo_pipx_spec "$SLO_REPO_FALLBACK_URL")"
    pipx install --force --python "$python_bin" "$spec"
}

slo_remote_available() {
    # Use the install interpreter to bound git's whole probe on macOS and Linux,
    # without relying on GNU timeout. Python is already provisioned by main.
    "$2" - "$1" <<'PY'
import subprocess
import sys

try:
    result = subprocess.run(
        ["git", "ls-remote", sys.argv[1]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
except subprocess.TimeoutExpired:
    sys.exit(1)
except OSError:
    sys.exit(0)  # Missing local git must not masquerade as a server outage.
sys.exit(0 if result.returncode == 0 else 1)
PY
}

# ---- 7. Shell environment finalisation (spec 80) ----------------------------
# After a successful pipx install, persist three *defaults* so fresh supported
# shells launch slo with an explicit SLO_HOME, SLO_SKILLS_DIR, and SLO_KB_DIR:
#   SLO_HOME=$HOME/.slo
#   SLO_SKILLS_DIR=<installed package location>/skills
#   SLO_KB_DIR=$KB_DIR, else $SLO_HOME/KnowledgeBase/KB
# `slo update` reaches the same code through `install.sh --finalize-environment`
# (run from the just-installed package) when any of them is missing.
# One installer-owned managed environment file ($HOME/.slo/shell/environment.sh)
# defines both defaults; shell profiles carry only a bounded source block that
# reads it. config/cfg.py remains the sole runtime resolver — the managed file
# feeds its existing explicit-environment branch and never replaces it.

slo_resolve_vendored_skills_dir() {
    # Resolve the vendored skills directory of the JUST-INSTALLED pipx package.
    #
    # The ONLY source of truth is pip distribution metadata:
    # `pipx runpip slo show slo` → its `Location:` field → `<Location>/skills`.
    # Guessing a pipx layout (venvs/slo/lib/pythonX.Y/site-packages), a repo
    # checkout, or $SLO_HOME/skills is PROHIBITED: any of those silently
    # couples persistent shell state to a Python version, a pipx default root,
    # or a checkout path that an upgrade can invalidate.
    #
    # stdout contract: exactly one canonical absolute path, no log prefix.
    # All diagnostics go to stderr; any failure returns non-zero.
    local show_output=""
    if ! show_output="$(pipx runpip slo show slo 2>/dev/null)"; then
        echo "error: 'pipx runpip slo show slo' failed; fix the pipx install and re-run this installer." >&2
        return 1
    fi
    local location="" line=""
    while IFS= read -r line; do
        case "$line" in
            "Location: "*)
                if [ -n "$location" ]; then
                    echo "error: ambiguous 'pipx runpip slo show slo' output: multiple Location fields." >&2
                    return 1
                fi
                location="${line#Location: }"
                ;;
        esac
    done <<< "$show_output"
    if [ -z "$location" ]; then
        echo "error: 'pipx runpip slo show slo' reported no Location field; refusing to guess the pipx layout." >&2
        return 1
    fi
    local candidate="$location/skills"
    if [ ! -d "$candidate" ]; then
        echo "error: vendored skills directory not found at $candidate (is the wheel complete?)." >&2
        return 1
    fi
    if [ ! -f "$candidate/INDEX.md" ] || [ ! -r "$candidate/INDEX.md" ]; then
        echo "error: no readable INDEX.md in $candidate; refusing to persist a broken SLO_SKILLS_DIR." >&2
        return 1
    fi
    # Canonicalise to the physical absolute path (no symlink components).
    local canonical=""
    if ! canonical="$(cd -- "$candidate" 2>/dev/null && pwd -P)"; then
        echo "error: failed to canonicalise the vendored skills directory at $candidate." >&2
        return 1
    fi
    echo "$canonical"
}

slo_shell_single_quote() {
    # POSIX-safe single-quote encoder: wraps "$1" in single quotes, replacing
    # every literal apostrophe with the standard close-quote, escaped
    # apostrophe, reopen-quote sequence. The result is safe to embed verbatim
    # in generated shell as a literal string (no expansion, no word splitting).
    local value="$1"
    printf "'%s'" "${value//\'/\'\\\'\'}"
}

slo_canonical_directory() {
    # Print the physical absolute path for an existing directory.
    local directory="$1"
    if [ ! -d "$directory" ]; then
        return 1
    fi
    (cd -- "$directory" 2>/dev/null && pwd -P)
}

slo_validate_venv_python() {
    # Validate the venv-side interpreter pathname without resolving it for the
    # wrapper. POSIX venvs normally make bin/python a link to a base interpreter
    # outside the venv; only executing the venv-side path can prove the active
    # sys.prefix remains this exact venv. Bound link traversal still rejects
    # cycles and malformed paths before process execution.
    local venv_root="$1" python_bin="$2" path="$2" resolved="" parent="" hops=0
    [ ! -L "$venv_root" ] && [ -f "$python_bin" ] && [ -x "$python_bin" ] || return 1
    while [ -L "$path" ]; do
        hops=$((hops + 1))
        [ "$hops" -le 16 ] || return 1
        resolved="$(readlink "$path" 2>/dev/null || true)"
        [ -n "$resolved" ] || return 1
        case "$resolved" in
            /*) path="$resolved" ;;
            *)
                parent="$(dirname "$path")"
                path="$parent/$resolved"
                ;;
        esac
    done
    [ -f "$path" ] && [ -x "$path" ] || return 1
    "$python_bin" -c 'import sys; print(sys.prefix)' 2>/dev/null | grep -Fx -- "$venv_root" >/dev/null
}

slo_is_safe_launcher_file() {
    # Return success only for a readable, non-symlink regular launcher file.
    local path="$1"
    [ ! -L "$path" ] && [ -f "$path" ] && [ -r "$path" ]
}

slo_read_safe_launcher() {
    # Print a bounded launcher only after rejecting links, non-files, and NUL bytes.
    local path="$1" size=""
    slo_is_safe_launcher_file "$path" || return 1
    size="$(wc -c < "$path" | tr -d ' ')"
    case "$size" in
        '' | *[!0-9]*) return 1 ;;
    esac
    [ "$size" -le 65536 ] || return 1
    if ! LC_ALL=C grep -Iq . "$path"; then
        return 1
    fi
    cat "$path"
}

slo_resolve_isolated_launcher_layout() {
    # Resolve and validate the pipx venv that owns the two generated scripts.
    # Stdout contract: exactly four key=value records; diagnostics use stderr.
    local pipx_home_raw="" pipx_home="" venv_root="" bin_dir=""
    local python_bin="" user_launcher="" entry_launcher="" show_output=""
    local location="" line="" location_parent="" prefix=""
    local python_prefix=""
    if ! pipx_home_raw="$(pipx environment --value PIPX_HOME 2>/dev/null)"; then
        echo "error: 'pipx environment --value PIPX_HOME' failed; refusing to guess the pipx layout." >&2
        return 1
    fi
    if [ -z "$pipx_home_raw" ] || [ "$(printf '%s\n' "$pipx_home_raw" | wc -l | tr -d ' ')" != "1" ] || [ "${pipx_home_raw#/}" = "$pipx_home_raw" ]; then
        echo "error: pipx reported an invalid PIPX_HOME; refusing to guess the pipx layout." >&2
        return 1
    fi
    if ! pipx_home="$(slo_canonical_directory "$pipx_home_raw")"; then
        echo "error: pipx PIPX_HOME is not a real directory: $pipx_home_raw" >&2
        return 1
    fi
    venv_root="$pipx_home/venvs/slo"
    # The named pipx application root is the outer trust boundary. Even a link
    # to a directory under PIPX_HOME is rejected: otherwise a later retarget
    # can redirect the finalizer's write without changing the reported root.
    if [ -L "$venv_root" ]; then
        echo "error: pipx slo venv directory is a symlink; refusing to follow it." >&2
        return 1
    fi
    bin_dir="$venv_root/bin"
    # Reject the bin directory as a link before canonicalization. A link may
    # resolve beneath this venv today but can later be retargeted to redirect
    # wrapper writes. The interpreter *inside* this direct child may still be
    # a normal venv link to an external base Python; that is validated below.
    if [ -L "$bin_dir" ]; then
        echo "error: pipx slo venv/bin directory is a symlink; refusing to follow it." >&2
        return 1
    fi
    if ! venv_root="$(slo_canonical_directory "$venv_root")" || ! bin_dir="$(slo_canonical_directory "$bin_dir")"; then
        echo "error: pipx slo venv/bin directory is unavailable under $pipx_home." >&2
        return 1
    fi
    if [ "$(dirname "$bin_dir")" != "$venv_root" ]; then
        echo "error: pipx canonical venv/bin is not a direct child of the validated venv; refusing to validate the launcher." >&2
        return 1
    fi
    python_bin="$bin_dir/python"
    user_launcher="$bin_dir/slo"
    entry_launcher="$bin_dir/slo-entry"
    if ! slo_validate_venv_python "$venv_root" "$python_bin" || ! slo_is_safe_launcher_file "$user_launcher"; then
        echo "error: pipx slo launcher artifacts are missing or unsafe under $bin_dir." >&2
        return 1
    fi
    if ! slo_is_safe_launcher_file "$entry_launcher"; then
        echo "error: generated slo-entry trampoline is missing or invalid under $bin_dir. Reinstall an 82.a+ Slo release." >&2
        return 1
    fi
    if ! show_output="$(pipx runpip slo show slo 2>/dev/null)"; then
        echo "error: 'pipx runpip slo show slo' failed; refusing to validate the launcher." >&2
        return 1
    fi
    while IFS= read -r line; do
        case "$line" in
            "Location: "*)
                if [ -n "$location" ]; then
                    echo "error: pipx metadata has multiple Location fields; refusing to validate the launcher." >&2
                    return 1
                fi
                location="${line#Location: }"
                ;;
        esac
    done <<< "$show_output"
    if [ -z "$location" ] || [ "${location#/}" = "$location" ]; then
        echo "error: pipx metadata has no single absolute Location; refusing to validate the launcher." >&2
        return 1
    fi
    if ! location_parent="$(slo_canonical_directory "$location")"; then
        echo "error: pipx metadata Location is not a real directory: $location" >&2
        return 1
    fi
    case "$location_parent" in "$venv_root"/*) ;; *)
        echo "error: pipx metadata Location is outside the validated slo venv; refusing to validate the launcher." >&2
        return 1
    esac
    # Keep the venv-side pathname intact in the generated shebang and wrapper.
    # Its exact sys.prefix was proved by slo_validate_venv_python above.
    printf 'venv_root=%s\npython_bin=%s\nuser_launcher=%s\nentry_launcher=%s\n' "$venv_root" "$python_bin" "$user_launcher" "$entry_launcher"
}

slo_render_isolated_launcher() {
    # Render the one canonical user-facing wrapper from validated absolute paths.
    local python_bin="$1" entry_launcher="$2"
    printf '%s\n' '#!/bin/sh' '# >>> slo isolated launcher (v1) >>>' '# Generated by the Slo installer; do not edit.' "exec $(slo_shell_single_quote "$python_bin") -I $(slo_shell_single_quote "$entry_launcher") \"\$@\""
}

slo_is_recognized_generated_launcher() {
    # Recognize only pip's src.cli:main console script. A pip/pipx-generated
    # shebang may retain venv/bin/python even when that validated path resolves
    # through contained links to the canonical executable used by the wrapper.
    # Those two paths, and no arbitrary same-venv pathname, are accepted.
    local launcher="$1" python_bin="$2" content="" expected_body="" shebang=""
    local venv_root="" original_python=""
    if ! content="$(slo_read_safe_launcher "$launcher")"; then
        return 1
    fi
    shebang="${content%%$'\n'*}"
    venv_root="$(dirname "$(dirname "$python_bin")")"
    original_python="$venv_root/bin/python"
    case "$shebang" in
        "#!$python_bin" | "#!$original_python") ;;
        *) return 1 ;;
    esac
    expected_body="# -*- coding: utf-8 -*-
import re
import sys
from src.cli import main

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])
    sys.exit(main())"
    if [ "${content#*$'\n'}" = "$expected_body" ]; then
        return 0
    fi
    # Current installers also generate this minimal Python 3 console script.
    # Accept its complete body, not just an import substring: extra executable
    # statements must still fail closed, and neither template is executed here.
    expected_body="import sys
from src.cli import main
if __name__ == '__main__':
    sys.argv[0] = sys.argv[0].removesuffix('.exe')
    sys.exit(main())"
    [ "${content#*$'\n'}" = "$expected_body" ]
}

slo_validate_isolated_launcher_stage() {
    # Prove a mktemp result is a new regular stage directly under the validated bin directory.
    local tmp_file="$1" target_dir="$2" expected_path="$3" canonical_parent=""
    [ -n "$tmp_file" ] && [ "$tmp_file" = "$expected_path" ] && [ ! -L "$tmp_file" ] && [ -f "$tmp_file" ] || return 1
    canonical_parent="$(slo_canonical_directory "$(dirname "$tmp_file")")" || return 1
    [ "$canonical_parent" = "$target_dir" ]
}

slo_remove_isolated_launcher_stage() {
    # Remove only a still-validated stage file, never an arbitrary mktemp result.
    local tmp_file="$1" target_dir="$2" expected_path="$3"
    if slo_validate_isolated_launcher_stage "$tmp_file" "$target_dir" "$expected_path"; then
        rm -f -- "$tmp_file"
    fi
}

slo_write_isolated_launcher() {
    # Atomically activate a canonical wrapper only over a recognized safe target.
    local user_launcher="$1" python_bin="$2" entry_launcher="$3"
    local canonical="" current="" marker_count="" tmp_file="" target_dir="" stage_template=""
    canonical="$(slo_render_isolated_launcher "$python_bin" "$entry_launcher")"
    if ! current="$(slo_read_safe_launcher "$user_launcher")"; then
        echo "error: refusing to replace $user_launcher: it is not a safe regular launcher file." >&2
        return 1
    fi
    if [ "$current" = "$canonical" ]; then
        slo_log "isolated launcher already current: $user_launcher"
        return 0
    fi
    marker_count="$(grep -cF -- '# >>> slo isolated launcher (' "$user_launcher" || true)"
    if [ "$marker_count" != "0" ] || ! slo_is_recognized_generated_launcher "$user_launcher" "$python_bin"; then
        echo "error: refusing to replace unrecognized or modified launcher: $user_launcher" >&2
        return 1
    fi
    target_dir="$(slo_canonical_directory "$(dirname "$user_launcher")")" || {
        echo "error: failed to validate isolated launcher target directory." >&2
        return 1
    }
    stage_template="$target_dir/.slo.XXXXXX"
    if ! tmp_file="$(mktemp "$stage_template")"; then
        echo "error: failed to stage isolated launcher in $target_dir." >&2
        return 1
    fi
    case "$tmp_file" in "$target_dir"/.slo.*) ;; *)
        echo "error: failed to stage isolated launcher in $target_dir." >&2
        return 1
        ;;
    esac
    if ! slo_validate_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file"; then
        echo "error: failed to stage isolated launcher in $target_dir." >&2
        return 1
    fi
    if ! slo_validate_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file" || ! printf '%s\n' "$canonical" > "$tmp_file"; then
        slo_remove_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file"
        echo "error: failed to write isolated launcher for $user_launcher." >&2
        return 1
    fi
    if ! slo_validate_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file" || ! slo_sync_file "$tmp_file"; then
        slo_remove_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file"
        echo "error: failed to sync staged isolated launcher for $user_launcher." >&2
        return 1
    fi
    if ! slo_validate_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file" || ! chmod 0755 "$tmp_file"; then
        slo_remove_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file"
        echo "error: failed to set isolated launcher mode for $user_launcher." >&2
        return 1
    fi
    # `mv` within the same directory is the portable atomic activation
    # operation. fsync is attempted through the optional Python helper below;
    # platforms without it retain atomic activation but report no stronger
    # durability guarantee.
    if ! slo_validate_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file" || ! mv -f "$tmp_file" "$user_launcher"; then
        slo_remove_isolated_launcher_stage "$tmp_file" "$target_dir" "$tmp_file"
        echo "error: failed to activate isolated launcher for $user_launcher." >&2
        return 1
    fi
    if ! slo_canonical_directory "$target_dir" >/dev/null || ! slo_sync_directory "$target_dir"; then
        # Rename has already activated the wrapper. Returning failure here would
        # falsely promise preservation while leaving changed bytes in place.
        # Keep activation successful and make the weaker durability result plain.
        echo "warning: isolated launcher was activated but its directory could not be synced: $target_dir; metadata durability is not confirmed." >&2
    fi
    slo_log "isolated launcher finalized: $user_launcher"
}

slo_sync_file() {
    # Flush one staged launcher using Python when it is available. A missing
    # helper is tolerated for portability; a present helper failure is fatal.
    local path="$1" python=""
    python="$(command -v python3 2>/dev/null || true)"
    [ -n "$python" ] || return 0
    "$python" - "$path" <<'PY'
import os
import sys

with open(sys.argv[1], "rb") as handle:
    os.fsync(handle.fileno())
PY
}

slo_sync_directory() {
    # Flush the directory entry after atomic activation where the platform
    # allows opening directories. Unsupported directory fsync is best effort.
    local directory="$1" python=""
    python="$(command -v python3 2>/dev/null || true)"
    [ -n "$python" ] || return 0
    "$python" - "$directory" <<'PY'
import errno
import os
import sys

try:
    descriptor = os.open(sys.argv[1], os.O_RDONLY)
except OSError as error:
    if error.errno in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
        raise SystemExit(0)
    raise
try:
    os.fsync(descriptor)
except OSError as error:
    if error.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
        raise
finally:
    os.close(descriptor)
PY
}

slo_finalize_isolated_launcher() {
    # Validate pipx artifacts then replace only its fresh generated user launcher.
    local layout="" line="" venv_root="" python_bin="" user_launcher="" entry_launcher=""
    if ! layout="$(slo_resolve_isolated_launcher_layout)"; then
        echo "error: slo code installed, but launcher hardening was not completed. Re-run the matching tagged public installer." >&2
        return 1
    fi
    while IFS='=' read -r key value; do
        case "$key" in
            venv_root) venv_root="$value" ;;
            python_bin) python_bin="$value" ;;
            user_launcher) user_launcher="$value" ;;
            entry_launcher) entry_launcher="$value" ;;
        esac
    done <<< "$layout"
    if ! slo_is_recognized_generated_launcher "$entry_launcher" "$python_bin"; then
        echo "error: entry launcher is not the expected generated src.cli trampoline; refusing to harden." >&2
        return 1
    fi
    slo_write_isolated_launcher "$user_launcher" "$python_bin" "$entry_launcher"
}

slo_write_managed_environment_file() {
    # Atomically write the installer-owned managed environment file.
    #
    # $HOME/.slo/shell/environment.sh is the ONLY persistent definition of the
    # three shell defaults. It supplies defaults only: a caller that exports
    # SLO_HOME, SLO_SKILLS_DIR, or SLO_KB_DIR before source time keeps that
    # value, which is what keeps config/cfg.py's explicit-override precedence
    # intact. SLO_KB_DIR falls back to KB_DIR, then $SLO_HOME/KnowledgeBase/KB;
    # only the variable is set, the directory is never created here. The file
    # is non-secret, so it is mode 0644: owner-writable for a rerun,
    # source-readable by the owning user's shells, never executable.
    #
    # Safety contract: an existing target must be a regular file carrying
    # exactly one complete Slo marker pair. Anything else (unmarked user file,
    # symlink, directory, device) is refused untouched — never deleted.
    local vendored_skills_dir="$1"
    if [ ! -d "$vendored_skills_dir" ]; then
        echo "error: vendored skills directory $vendored_skills_dir does not exist; not writing the managed environment file." >&2
        return 1
    fi
    local managed_file="$HOME/.slo/shell/environment.sh"
    local mark_begin="# >>> slo managed environment >>>"
    local mark_end="# <<< slo managed environment <<<"
    local quoted_skills_dir=""
    quoted_skills_dir="$(slo_shell_single_quote "$vendored_skills_dir")"
    local content="$mark_begin
# This file is generated by the Slo installer. Edit shell profiles, not this file.
if [ -z \"\${SLO_HOME+x}\" ]; then
    export SLO_HOME=\"\$HOME/.slo\"
fi
if [ -z \"\${SLO_SKILLS_DIR+x}\" ]; then
    export SLO_SKILLS_DIR=$quoted_skills_dir
fi
if [ -z \"\${SLO_KB_DIR+x}\" ]; then
    if [ -n \"\${KB_DIR:-}\" ]; then
        export SLO_KB_DIR=\"\$KB_DIR\"
    else
        export SLO_KB_DIR=\"\$SLO_HOME/KnowledgeBase/KB\"
    fi
fi
$mark_end"
    if [ -L "$managed_file" ]; then
        echo "error: refusing to overwrite $managed_file: it is a symlink. Move it aside deliberately and re-run." >&2
        return 1
    fi
    if [ -e "$managed_file" ] && [ ! -f "$managed_file" ]; then
        echo "error: refusing to overwrite $managed_file: it is not a regular file. Move it aside deliberately and re-run." >&2
        return 1
    fi
    if [ -f "$managed_file" ]; then
        local begin_count end_count
        # `|| true`: grep exits 1 when there are no matches, and under
        # `set -e` that aborts the substitution before we can refuse cleanly.
        begin_count="$(grep -cF -- "$mark_begin" "$managed_file" || true)"
        end_count="$(grep -cF -- "$mark_end" "$managed_file" || true)"
        if [ "$begin_count" != "1" ] || [ "$end_count" != "1" ]; then
            echo "error: refusing to overwrite $managed_file: it does not carry exactly one Slo managed-environment marker pair. Move it aside deliberately and re-run." >&2
            return 1
        fi
        if cmp -s "$managed_file" - <<< "$content"; then
            slo_log "managed environment file already current: $managed_file"
            return 0
        fi
    fi
    mkdir -p "$HOME/.slo/shell"
    local tmp_file=""
    if ! tmp_file="$(mktemp "$HOME/.slo/shell/.environment.sh.XXXXXX")"; then
        echo "error: failed to stage the managed environment file at $managed_file." >&2
        return 1
    fi
    chmod 0644 "$tmp_file"
    if ! printf '%s\n' "$content" > "$tmp_file"; then
        rm -f "$tmp_file"
        echo "error: failed to write the managed environment file at $managed_file." >&2
        return 1
    fi
    if ! mv -f "$tmp_file" "$managed_file"; then
        rm -f "$tmp_file"
        echo "error: failed to activate the managed environment file at $managed_file." >&2
        return 1
    fi
    slo_log "managed environment file written: $managed_file"
}

slo_shell_source_block() {
    # Echo the canonical shell source block: the ONLY text the installer ever
    # adds to a profile. It sources the managed environment file behind a
    # readable-file guard and declares no variables itself — the managed file
    # is the single owner of both defaults.
    local mark_begin="# >>> slo managed environment >>>"
    local mark_end="# <<< slo managed environment <<<"
    printf '%s\n' "$mark_begin
if [ -r \"\$HOME/.slo/shell/environment.sh\" ]; then
    . \"\$HOME/.slo/shell/environment.sh\"
fi
$mark_end"
}

slo_reconcile_shell_source_block() {
    # Safely add or refresh exactly one Slo shell source block in one profile.
    #
    # Decision contract (never guesses):
    #   missing file            → create it with one block
    #   no markers              → append one block, preserving all content
    #   one complete marker pair→ replace only that block, preserving the rest
    #                             byte-for-byte; identical bytes → already current
    #   malformed/multiple      → refuse, leave the file untouched, return 1
    #
    # The profile is NEVER sourced or executed: markers are matched as fixed
    # strings only.
    local profile_path="$1"
    local mark_begin="# >>> slo managed environment >>>"
    local mark_end="# <<< slo managed environment <<<"
    local block=""
    block="$(slo_shell_source_block)"
    if [ -L "$profile_path" ]; then
        echo "error: refusing to edit $profile_path: it is a symlink. Repair it deliberately and re-run." >&2
        return 1
    fi
    if [ ! -e "$profile_path" ]; then
        if ! printf '%s\n' "$block" > "$profile_path"; then
            echo "error: failed to create $profile_path with the Slo shell source block." >&2
            return 1
        fi
        slo_log "shell source block written: $profile_path"
        return 0
    fi
    if [ ! -f "$profile_path" ]; then
        echo "error: refusing to edit $profile_path: it is not a regular file. Repair it deliberately and re-run." >&2
        return 1
    fi
    local begin_count end_count
    begin_count="$(grep -cF -- "$mark_begin" "$profile_path" || true)"
    end_count="$(grep -cF -- "$mark_end" "$profile_path" || true)"
    if [ "$begin_count" = "0" ] && [ "$end_count" = "0" ]; then
        # Append after a separating newline; add a trailing newline to a file
        # that lacks one so the block never glues onto user content.
        if [ -s "$profile_path" ] && [ "$(tail -c 1 "$profile_path" | wc -l)" = "0" ]; then
            printf '\n' >> "$profile_path"
        fi
        {
            printf '\n'
            printf '%s\n' "$block"
        } >> "$profile_path"
        slo_log "shell source block appended: $profile_path"
        return 0
    fi
    if [ "$begin_count" != "1" ] || [ "$end_count" != "1" ]; then
        echo "error: refusing to edit $profile_path: found $begin_count begin and $end_count end Slo markers (expected exactly one pair). Repair the file manually and re-run." >&2
        return 1
    fi
    # Exactly one pair: refuse nested (begin inside begin..end) or reversed
    # markers rather than risk deleting user configuration.
    local first_begin first_end
    first_begin="$(grep -nF -- "$mark_begin" "$profile_path" | head -n 1 | cut -d: -f1)"
    first_end="$(grep -nF -- "$mark_end" "$profile_path" | head -n 1 | cut -d: -f1)"
    if [ "$first_end" -le "$first_begin" ]; then
        echo "error: refusing to edit $profile_path: Slo end marker appears before the begin marker. Repair the file manually and re-run." >&2
        return 1
    fi
    local current_block=""
    current_block="$(sed -n "${first_begin},${first_end}p" "$profile_path")"
    if [ "$current_block" = "$block" ]; then
        slo_log "shell source block already current: $profile_path"
        return 0
    fi
    # Streamed same-directory construction + atomic rename. NEVER rebuild the
    # file through command substitution (`updated="$(...)"`): that strips
    # every trailing newline byte and breaks the contract that content outside
    # the replaced marker pair is preserved byte-for-byte. Here the bytes
    # before the pair and after it (including a trailing blank-line run) are
    # copied to the staged file exactly as they exist on disk.
    local tmp_file=""
    tmp_file="$(mktemp "${profile_path}.slo.XXXXXX")"
    if ! {
        if [ "$first_begin" -gt 1 ]; then
            sed "1,$((first_begin - 1))!d" "$profile_path"
        fi
        printf '%s\n' "$block"
        sed "$((first_end + 1)),\$!d" "$profile_path"
    } > "$tmp_file"; then
        rm -f "$tmp_file"
        echo "error: failed to stage the updated $profile_path." >&2
        return 1
    fi
    if ! mv -f "$tmp_file" "$profile_path"; then
        rm -f "$tmp_file"
        echo "error: failed to activate the updated $profile_path." >&2
        return 1
    fi
    slo_log "shell source block updated: $profile_path"
}

slo_install_shell_environment() {
    # Apply the fixed supported-shell profile matrix.
    #
    # Bash login reads .bash_profile; interactive non-login Bash reads .bashrc;
    # .zshenv is read by every Zsh (login and non-login); .profile is the
    # POSIX login-shell and unknown-shell fallback. Descendant non-interactive
    # shells of those configured shells inherit the exports. Deliberately
    # sterile processes (env -i, bash --noprofile --norc, cron, services, GUI
    # launchers) cannot be configured by an installer and keep config/cfg.py's
    # fallback resolution — that boundary is documented, not hidden.
    local profile=""
    for profile in "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.zshenv" "$HOME/.profile"; do
        slo_reconcile_shell_source_block "$profile" || return 1
    done
}

slo_finalize_shell_environment() {
    # Post-install finalisation gateway: resolve → write managed file →
    # reconcile profiles. Called from main ONLY after `pipx install` succeeds,
    # so a failed install can never persist a new SLO_SKILLS_DIR. A failure
    # here means the package was installed but shell environment setup failed;
    # the message names the stage and the run exits non-zero without rolling
    # back the pipx venv or any user runtime data.
    local vendored_skills_dir=""
    if ! vendored_skills_dir="$(slo_resolve_vendored_skills_dir)"; then
        echo "error: slo code installed, but shell environment finalisation failed while resolving the vendored skills directory (see above). Fix the issue and re-run this installer." >&2
        return 1
    fi
    slo_log "resolved vendored skills directory: $vendored_skills_dir"
    if ! slo_write_managed_environment_file "$vendored_skills_dir"; then
        echo "error: slo code installed, but shell environment finalisation failed while writing the managed environment file (see above). Fix the issue and re-run this installer." >&2
        return 1
    fi
    if ! slo_install_shell_environment; then
        echo "error: slo code installed, but shell environment finalisation failed while updating shell profiles (see above). Repair the named profile and re-run this installer." >&2
        return 1
    fi
    slo_log "shell environment configured: open a new shell, or source ~/.slo/shell/environment.sh"
}

slo_ensure_local_bin_on_path() {
    # Detect the user's shell and ensure ~/.local/bin is on PATH in the rc file.
    # Idempotent: skips silently if the export line is already present in the rc
    # file, or if ~/.local/bin is already on the current PATH env var.
    local export_line='export PATH="$HOME/.local/bin:$PATH"'
    local rc_file=""

    # Detect rc file from $SHELL
    case "${SHELL:-}" in
        */zsh) rc_file="$HOME/.zshrc" ;;
        */bash)
            # Prefer .bash_profile on macOS (login shell), .bashrc on Linux
            if [ "$(slo_os_kind)" = "macos" ] && [ -f "$HOME/.bash_profile" ]; then
                rc_file="$HOME/.bash_profile"
            else
                rc_file="$HOME/.bashrc"
            fi
            ;;
        *)
            # Unknown shell — fall back to ~/.profile
            rc_file="$HOME/.profile"
            ;;
    esac

    # Check current PATH env var first (already active in this session)
    case ":${PATH}:" in
        *":$HOME/.local/bin:"*)
            slo_log "~/.local/bin is already on PATH — no rc update needed"
            return 0
            ;;
    esac

    # Check if the export line is already in the rc file (idempotency guard)
    if [ -f "$rc_file" ] && grep -qF '.local/bin' "$rc_file" 2>/dev/null; then
        slo_log "~/.local/bin already referenced in $rc_file — skipping"
        return 0
    fi

    # Append the export to the rc file
    {
        echo ""
        echo "# Added by slo installer"
        echo "$export_line"
    } >> "$rc_file"

    slo_log "Added ~/.local/bin to PATH in $rc_file"
    slo_log "Restart your shell or run: source $rc_file"
}

slo_print_path() {
    # Print the verify / upgrade / uninstall cheatsheet.
    cat >&2 <<EOF

slo installed via pipx.

PATH updated: restart your shell (or 'source' the rc file named in the log line above).

Verify:    slo --help
Upgrade / repair: re-run the matching tagged public Slo installer.
Direct pipx install, upgrade, or reinstall regenerates entry scripts but does not
run Slo launcher finalisation; it is not a supported repair path.
Uninstall: pipx uninstall slo

Runtime data (sessions, logs, credentials) lives in \${SLO_HOME:-~/.slo} and is
left untouched by install, upgrade, and uninstall.
EOF
}

# ---- main dispatch ---------------------------------------------------------
main() {
    # `--development` is an explicit alias for tracking the main branch (the
    # default); pin a release instead with SLO_REF=<tag>.
    # Dedicated finalizer modes never provision tooling, reinstall code, or inspect
    # project configuration. The updater runs launcher finalization after pipx.
    if [ "${1:-}" = "--finalize-launcher" ]; then
        slo_finalize_isolated_launcher
        return
    fi
    if [ "${1:-}" = "--finalize-environment" ]; then
        slo_finalize_shell_environment
        return
    fi
    if [ "${1:-}" = "--development" ]; then
        SLO_REF="main"
    fi
    slo_ensure_brew
    slo_ensure_git
    slo_ensure_build_deps
    slo_ensure_pyenv
    slo_ensure_python
    slo_ensure_pipx
    slo_ensure_home >/dev/null
    slo_install
    slo_finalize_shell_environment
    slo_finalize_isolated_launcher
    slo_ensure_local_bin_on_path
    slo_print_path
}

# Run main only when executed directly. When sourced (e.g. by the unit tests),
# `return` succeeds and main is skipped so individual functions can be tested.
if ! (return 0 2>/dev/null); then
    main "$@"
fi
