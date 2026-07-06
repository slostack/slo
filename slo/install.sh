#!/usr/bin/env bash
# install.sh — one-line installer for slo.
#
#   curl -fsSL <url>/install.sh | SLO_USERNAME='<user>' SLO_TOKEN='<token>' bash
#
# Installs slo as a normal pipx application straight from its git repository.
# pipx builds the package in its own isolated venv and puts the `slo` binary on
# your PATH. NOTHING is written to SLO_HOME (~/.slo) — that directory is slo's
# *runtime data* (sessions, logs, credentials), NOT a code checkout. The old
# installer cloned the repo into ~/.slo, which collides with that data and
# aborts ("destination path already exists") on any machine where slo has run.
#
# On a bare machine this first provisions the toolchain pipx needs. macOS uses
# Homebrew for pyenv, git, and pipx. Debian-family Linux uses apt for git,
# pyenv's build headers, and pipx, then git-clones pyenv itself before building
# the pinned Python (3.11.x). Every step is a no-op when already satisfied, so
# re-running upgrades slo in place. No interactive prompts.
#
# Configuration (all overridable from the environment):
#   SLO_USERNAME       credential username for the private repo fetch
#   SLO_TOKEN          credential secret for the private repo fetch
#   SLO_DEPLOY_TOKEN_USERNAME / SLO_DEPLOY_TOKEN
#                      GitLab deploy token (authenticates as <user>:<token>)
#   SLO_INSTALL_TOKEN  personal access token (injected as oauth2:<token>);
#                      used only when no deploy token is set
#   SLO_VERSION        version to install (default: pinned release baked in at
#                      publish time). Pass "dev" to track the main branch.
#   SLO_REPO_URL       git URL to install from (default below)
#   SLO_PYTHON_VERSION pinned interpreter version (default: 3.11.7)
#
# Testability: every function below is sourceable. The `main` dispatch at the
# bottom runs only when the script is executed directly, not when sourced — so
# the unit tests in tests/cli/test_install.py can source this file and exercise
# each function against a stubbed PATH without mutating the host.
set -euo pipefail

# ---- Configuration (single source of truth) --------------------------------
SLO_REPO_URL="${SLO_REPO_URL:-https://gitlab.com/core-27/slo.git}"
SLO_REF="${SLO_REF:-main}"
SLO_PYTHON_VERSION="${SLO_PYTHON_VERSION:-3.11.7}"

# ---- User-facing credential and version aliases ----------------------------
# SLO_USERNAME / SLO_TOKEN are the public names; map to internal deploy-token
# vars used by slo_pipx_spec(). SLO_VERSION controls the git ref to install:
#   unset / empty → use SLO_REF (default pinned at publish time by deploy script)
#   "dev"         → main branch
#   anything else → treated as a release tag or branch name
SLO_DEPLOY_TOKEN_USERNAME="${SLO_USERNAME:-${SLO_DEPLOY_TOKEN_USERNAME:-}}"
SLO_DEPLOY_TOKEN="${SLO_TOKEN:-${SLO_DEPLOY_TOKEN:-}}"
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
    # On an https URL, inject a credential for this run. Two mechanisms, in
    # precedence order (matches docs/INSTALL.md):
    #   1. GitLab deploy token: SLO_DEPLOY_TOKEN_USERNAME + SLO_DEPLOY_TOKEN
    #      authenticate as <user>:<token>.
    #   2. Personal access token: SLO_INSTALL_TOKEN, injected as oauth2:<token>.
    # Credentials with URL-reserved characters (e.g. ':' '@' '/') must be
    # percent-encoded by the caller. The credential is only ever passed to git
    # for this fetch — it is not written to disk by this script.
    local url="$SLO_REPO_URL"
    local rest="${url#https://}"
    if [ "$rest" != "$url" ]; then
        if [ -n "${SLO_DEPLOY_TOKEN_USERNAME:-}" ] && [ -n "${SLO_DEPLOY_TOKEN:-}" ]; then
            url="https://${SLO_DEPLOY_TOKEN_USERNAME}:${SLO_DEPLOY_TOKEN}@${rest}"
        elif [ -n "${SLO_INSTALL_TOKEN:-}" ]; then
            url="https://oauth2:${SLO_INSTALL_TOKEN}@${rest}"
        fi
    fi
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
    # pipx auto-selects a uv backend whenever any `uv` is on PATH but never
    # checks that it runs; a stale pyenv `uv` shim (uv present only in some
    # virtualenvs) then aborts the install. Fall back to pip when uv is present
    # but not runnable, unless the caller already pinned a backend.
    if [ -z "${PIPX_DEFAULT_BACKEND:-}" ] && slo_has uv && ! uv --version >/dev/null 2>&1; then
        slo_log "uv on PATH is not runnable; forcing pipx pip backend"
        export PIPX_DEFAULT_BACKEND=pip
    fi
    local spec python_bin
    spec="$(slo_pipx_spec)"
    python_bin="$(slo_python_bin)"
    slo_log "installing slo via pipx (python: $python_bin) from ${SLO_REPO_URL}@${SLO_REF}"
    pipx install --force --python "$python_bin" "$spec"
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
Upgrade:   re-run this installer, or:
           pipx install --force "git+${SLO_REPO_URL}@${SLO_REF}"
Uninstall: pipx uninstall slo

Runtime data (sessions, logs, credentials) lives in \${SLO_HOME:-~/.slo} and is
left untouched by install, upgrade, and uninstall.
EOF
}

# ---- main dispatch ---------------------------------------------------------
main() {
    # `--development` is an explicit alias for tracking the main branch (the
    # default); pin a release instead with SLO_REF=<tag>.
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
    slo_ensure_local_bin_on_path
    slo_print_path
}

# Run main only when executed directly. When sourced (e.g. by the unit tests),
# `return` succeeds and main is skipped so individual functions can be tested.
if ! (return 0 2>/dev/null); then
    main "$@"
fi
