#!/usr/bin/env bash
# install_smoke_container.sh — hermetic in-container smoke for the public installer.
#
# WHO runs this: tests/cli/test_install_smoke.py, inside a fresh Docker
# container whose ONLY mount is the repository source parent at /src:ro.
# WHAT it proves (spec 80.a.2, M1):
#   * the installer runs from a fresh writable copy — never the read-only
#     mounted /src/install.sh — once per install run;
#   * all runtime roots (HOME, XDG, pipx, pyenv) live in-container only;
#   * finalisation writes a 0644 managed environment file whose SLO_SKILLS_DIR
#     is a real absolute path with a readable INDEX.md and is NOT ~/.slo/skills;
#   * fresh Bash login and interactive non-login shells, and Zsh login and
#     interactive non-login shells, export both defaults;
#   * an explicit source-time override survives the managed file;
#   * a user skill under ~/.slo/user_skills survives while user_workflows and
#     ~/.slo/skills stay absent;
#   * a second install run (second fresh copy) is idempotent: one marker pair
#     per profile, valid managed file, working `slo --help`.
# WHEN: after the container has installed curl/ca-certificates/zsh. This
# script never touches a host path; every writable location is under /tmp.

set -euo pipefail

fail() {
    echo "SMOKE-FAIL: $*" >&2
    exit 1
}

MARK_BEGIN="# >>> slo managed environment >>>"
MARK_END="# <<< slo managed environment <<<"

count_lines() {
    # Count pattern occurrences in a file, defaulting to 0 on no match.
    local pattern="$1" file="$2"
    grep -cF -- "$pattern" "$file" 2>/dev/null || true
}

# ---- Isolated in-container roots ------------------------------------------
export HOME
HOME="$(mktemp -d /tmp/slo-home.XXXXXX)"
export XDG_CONFIG_HOME="$HOME/xdg-config"
export XDG_DATA_HOME="$HOME/xdg-data"
export XDG_CACHE_HOME="$HOME/xdg-cache"
export PIPX_HOME="$HOME/pipx-home"
export PIPX_BIN_DIR="$HOME/pipx-bin"
export PYENV_ROOT="$HOME/pyenv"
export PATH="$PIPX_BIN_DIR:$PATH"
unset SLO_HOME SLO_SKILLS_DIR || true

MANAGED_FILE="$HOME/.slo/shell/environment.sh"

# M1: every install run executes a FRESH writable copy of the read-only mount.
run_public_installer() {
    local installer_copy=""
    installer_copy="$(mktemp /tmp/slo-install.XXXXXX)"
    cp /src/install.sh "$installer_copy"
    chmod 0700 "$installer_copy"
    bash "$installer_copy"
    rm -f "$installer_copy"
}

assert_shell_defaults() {
    # $1: human-readable shell mode label; remaining args: the shell command.
    local label="$1"
    shift
    local output=""
    output="$("$@" 2>/dev/null || true)"
    [ -n "$output" ] || fail "$label produced no output"
    local got_home got_skills
    got_home="$(printf '%s\n' "$output" | sed -n '1p')"
    got_skills="$(printf '%s\n' "$output" | sed -n '2p')"
    [ "$got_home" = "$HOME/.slo" ] || fail "$label exported SLO_HOME=$got_home (expected $HOME/.slo)"
    [ -n "$got_skills" ] || fail "$label exported an empty SLO_SKILLS_DIR"
    [ -f "$got_skills/INDEX.md" ] || fail "$label SLO_SKILLS_DIR has no INDEX.md: $got_skills"
    [ "$got_skills" != "$HOME/.slo/skills" ] || fail "$label SLO_SKILLS_DIR points at the Slo home"
    echo "smoke: $label exports OK ($got_skills)"
}

print_exports='printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"'

# ---- Install run 1 ----------------------------------------------------------
run_public_installer

[ -f "$MANAGED_FILE" ] || fail "managed environment file missing: $MANAGED_FILE"
mode="$(stat -c '%a' "$MANAGED_FILE")"
[ "$mode" = "644" ] || fail "managed environment file mode is $mode, expected 644"
[ "$(count_lines "$MARK_BEGIN" "$MANAGED_FILE")" = "1" ] || fail "managed file begin-marker count != 1"
[ "$(count_lines "$MARK_END" "$MANAGED_FILE")" = "1" ] || fail "managed file end-marker count != 1"

# Source the managed file directly and validate the persisted vendored path.
resolved_skills="$(bash --noprofile --norc -c ". \"$MANAGED_FILE\"; printf '%s' \"\$SLO_SKILLS_DIR\"")"
[ -n "$resolved_skills" ] || fail "managed file exported an empty SLO_SKILLS_DIR"
[ -f "$resolved_skills/INDEX.md" ] || fail "persisted SLO_SKILLS_DIR has no INDEX.md: $resolved_skills"
[ "$resolved_skills" != "$HOME/.slo/skills" ] || fail "persisted SLO_SKILLS_DIR points at the Slo home"
echo "smoke: managed environment file OK (skills at $resolved_skills)"

for profile in .bash_profile .bashrc .zshenv .profile; do
    [ -f "$HOME/$profile" ] || fail "profile missing after install: $profile"
    [ "$(count_lines "$MARK_BEGIN" "$HOME/$profile")" = "1" ] || fail "$profile begin-marker count != 1"
    [ "$(count_lines "$MARK_END" "$HOME/$profile")" = "1" ] || fail "$profile end-marker count != 1"
done

# ---- Fresh shells -----------------------------------------------------------
assert_shell_defaults "bash --login" bash --login -c "$print_exports"
assert_shell_defaults "bash -i" bash -i -c "$print_exports"
if command -v zsh >/dev/null 2>&1; then
    assert_shell_defaults "zsh --login" zsh --login -c "$print_exports"
    assert_shell_defaults "zsh -i" zsh -i -c "$print_exports"
else
    fail "zsh is expected in the smoke image but was not found"
fi

# POSIX login fallback: dash-as-sh reads .profile when started as a login shell.
if command -v dash >/dev/null 2>&1; then
    posix_out="$(env -i HOME="$HOME" PATH="$PATH" TERM=dumb dash -l -c "$print_exports" 2>/dev/null || true)"
    posix_home="$(printf '%s\n' "$posix_out" | sed -n '1p')"
    [ "$posix_home" = "$HOME/.slo" ] || fail "POSIX login shell did not export SLO_HOME (got: $posix_home)"
    echo "smoke: POSIX .profile fallback OK"
fi

# Explicit source-time overrides must survive the managed file.
override_out="$(env SLO_HOME=/custom/slo-home SLO_SKILLS_DIR=/custom/skills bash --login -c "$print_exports")"
[ "$(printf '%s\n' "$override_out" | sed -n '1p')" = "/custom/slo-home" ] || fail "explicit SLO_HOME override lost"
[ "$(printf '%s\n' "$override_out" | sed -n '2p')" = "/custom/skills" ] || fail "explicit SLO_SKILLS_DIR override lost"
echo "smoke: explicit overrides survive OK"

# ---- User content ------------------------------------------------------------
user_skill="$HOME/.slo/user_skills/smoke-skill/SKILL.md"
mkdir -p "$(dirname "$user_skill")"
cat > "$user_skill" <<'SKILL'
---
name: smoke-skill
description: Smoke-test user skill.
when_to_use: Never; smoke fixture only.
group: coding
kind: skill
---
SKILL

# Non-provider seam: prove the INSTALLED config/cfg.py resolver and
# SkillsLoader honour the managed environment, without any provider call. The
# snippet runs inside a fresh bash login shell, so .bash_profile sources the
# managed environment file first and cfg.py's explicit-environment branch must
# resolve SLO_SKILLS_DIR to the installed vendored tree.
"$PIPX_BIN_DIR/slo" --help >/dev/null || fail "slo --help failed after install"
python_bin="$PIPX_HOME/venvs/slo/bin/python"
[ -x "$python_bin" ] || fail "no python interpreter found at $python_bin"
# Stage the proof snippet to a file so bash --login -c receives a single word
# (the script path) — no multi-word quoting inside the outer -c command string.
proof_script="$(mktemp /tmp/slo-proof.XXXXXX.py)"
cat > "$proof_script" <<'PYEOF'
import sys

from config.cfg import SKILLS_DIR, USER_SKILLS_DIR, USER_WORKFLOWS_DIR
from src.agents.slo_agent.skills.service import SkillsLoader

entries = SkillsLoader.load_merged(
    vendored_skills_dir=SKILLS_DIR,
    user_skills_dir=USER_SKILLS_DIR,
    user_workflows_dir=USER_WORKFLOWS_DIR,
)
names = {entry.name for entry in entries}
print(f"SKILLS_DIR={SKILLS_DIR}")
print(f"USER_SKILLS_DIR={USER_SKILLS_DIR}")
print(f"USER_WORKFLOWS_DIR={USER_WORKFLOWS_DIR}")
print(f"SKILL_COUNT={len(entries)}")
print(f"HAS_SMOKE_SKILL={'smoke-skill' in names}")
sys.exit(0)
PYEOF
loader_report="$(bash --login -c "$python_bin $proof_script" 2>/dev/null)" || fail "installed config/SkillsLoader proof failed to run"
rm -f "$proof_script"
report_skills_dir="$(printf '%s\n' "$loader_report" | sed -n 's/^SKILLS_DIR=//p')"
[ "$report_skills_dir" = "$resolved_skills" ] || fail "cfg.py resolved SKILLS_DIR=$report_skills_dir, expected $resolved_skills"
[ -n "$report_skills_dir" ] || fail "cfg.py resolved an empty SKILLS_DIR"
report_count="$(printf '%s\n' "$loader_report" | sed -n 's/^SKILL_COUNT=//p')"
[ "${report_count:-0}" -gt 0 ] || fail "SkillsLoader found zero vendored skills"
[ "$(printf '%s\n' "$loader_report" | sed -n 's/^HAS_SMOKE_SKILL=//p')" = "True" ] || fail "user skill 'smoke-skill' missing from the merged load"
[ -d "$HOME/.slo/user_skills" ] || fail "user_skills directory missing"
[ ! -e "$HOME/.slo/user_workflows" ] || fail "user_workflows must stay absent (tolerated as empty)"
echo "smoke: installed cfg.py + SkillsLoader resolve the managed skills dir and merge the user skill OK"
[ -f "$user_skill" ] || fail "user skill was modified by the installer"
[ ! -e "$HOME/.slo/user_workflows" ] || fail "user_workflows must stay absent"
[ ! -e "$HOME/.slo/skills" ] || fail "no copied vendored skills tree may appear under the Slo home"
echo "smoke: install run 1 OK (slo --help works, user content untouched)"

# ---- Install run 2 (fresh copy; idempotency) ---------------------------------
run_public_installer

for profile in .bash_profile .bashrc .zshenv .profile; do
    [ "$(count_lines "$MARK_BEGIN" "$HOME/$profile")" = "1" ] || fail "$profile has duplicate blocks after rerun"
    [ "$(count_lines "$MARK_END" "$HOME/$profile")" = "1" ] || fail "$profile has duplicate end markers after rerun"
done
[ -f "$MANAGED_FILE" ] || fail "managed environment file missing after rerun"
rerun_skills="$(bash --noprofile --norc -c ". \"$MANAGED_FILE\"; printf '%s' \"\$SLO_SKILLS_DIR\"")"
[ -f "$rerun_skills/INDEX.md" ] || fail "rerun SLO_SKILLS_DIR has no INDEX.md: $rerun_skills"
[ ! -e "$HOME/.slo/skills" ] || fail "rerun created a copied vendored skills tree"
[ -f "$user_skill" ] || fail "rerun touched the user skill"
"$PIPX_BIN_DIR/slo" --help >/dev/null || fail "slo --help failed after rerun"
echo "smoke: install run 2 OK (idempotent, no duplicates)"

echo "SMOKE-OK"
