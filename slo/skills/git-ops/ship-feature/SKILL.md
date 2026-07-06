---
name: ship-feature
description: Stage and commit all feature code with a detailed commit message, push the branch, open a GitLab MR or GitHub PR, merge it, then checkout main and pull the latest.
when_to_use: Use when the user asks to ship, commit, push, merge, or land a feature that is already implemented. Covers the full lifecycle from staged diff to clean main. Works on both GitLab (glab) and GitHub (gh).
group: git-ops
kind: workflow
---

# Ship Feature

## Skill summary

- **Name:** `ship-feature`
- **Description:** Stage and commit all feature code with a detailed commit message, push the branch, open a GitLab MR or GitHub PR, merge it, then checkout main and pull the latest.
- **When to use:** Use when the user asks to ship, commit, push, merge, or land a feature that is already implemented. Covers the full lifecycle from staged diff to clean main. Works on both GitLab (glab) and GitHub (gh).
- **Group:** `git-ops`
- **Kind:** `workflow`

## Examples

- "Ship the feature we just implemented."
- "Commit, push, open an MR, and merge it."
- "Land this on main."
- "Create a PR and merge it when it's ready."

## Guidance

---

## Mode

**Confirm-first mode is the default**, consistent with the rest of git-ops
(`commit-and-push` waits for confirmation; `create-pull-request` never
auto-merges unless asked). The agent PAUSES at two mandatory gates and awaits
explicit approval:

| Gate | Confirm-first (default) | Auto mode (opt-in only) |
|---|---|---|
| Before pushing to remote | **PAUSE — show diff summary, await confirmation** | Proceed silently |
| Before merging MR/PR | **PAUSE — show MR/PR URL, await confirmation** | Proceed silently |

**Auto mode is OPT-IN.** Enable it only when the user explicitly asks to run the
whole thing end-to-end without stopping, e.g.:
- "ship it" / "ship it end-to-end"
- "run the whole thing, don't ask me"
- "auto-merge it" / "push and merge without confirmation"
- auto mode is explicitly turned on

Absent such an explicit instruction, stay in confirm-first mode. The
"show the commit message before committing" gate (Step 5) always applies,
in either mode.

---

## Pre-conditions

Confirm before starting:

1. The working tree is on a feature branch (not `main` or `master`).
2. There are staged or unstaged changes to commit, OR the branch already has unpushed commits.
3. The branch does not already have an open MR/PR for the same content (check with `glab mr list` / `gh pr list`).

If the branch is `main`, stop immediately and route into `create-feature-branch` first.

---

## Step 1 — Detect platform

```bash
# Check remote URL to determine platform
git remote get-url origin
```

- URL contains `gitlab.com` or a self-hosted GitLab host → **GitLab path** (use `glab`)
- URL contains `github.com` → **GitHub path** (use `gh`)

If the platform cannot be determined from the remote URL, ask the user.

---

## Step 2 — Ensure CLI tool is installed

### GitLab

```bash
glab version 2>/dev/null || echo "NOT_INSTALLED"
```

If not installed:
```bash
# macOS
brew install glab

# Linux (apt)
sudo apt install glab

# Linux (curl fallback)
curl -sLO "https://gitlab.com/gitlab-org/cli/-/releases/permalink/latest/downloads/glab_$(uname -s)_$(uname -m).tar.gz" \
  && tar xzf glab_*.tar.gz && sudo mv bin/glab /usr/local/bin/

# Verify auth
glab auth status
```

If `glab auth status` fails, stop and tell the user:
```
glab is not authenticated. Run: glab auth login
```

### GitHub

```bash
gh version 2>/dev/null || echo "NOT_INSTALLED"
```

If not installed:
```bash
# macOS
brew install gh

# Linux (apt)
sudo apt install gh

# Linux (curl fallback — install script)
curl -sS https://webi.sh/gh | sh

# Verify auth
gh auth status
```

If `gh auth status` fails, stop and tell the user:
```
gh is not authenticated. Run: gh auth login
```

---

## Step 3 — Inspect current state

```bash
git status --short --branch
git diff --stat HEAD
git log --oneline origin/main..HEAD 2>/dev/null || git log --oneline -5
```

Capture:
- Branch name
- List of changed files (staged + unstaged)
- Any commits already ahead of main

---

## Step 4 — Stage files

Stage only the files relevant to the feature. Never use `git add -A` or `git add .` blindly.

Preferred: stage by explicit path
```bash
git add <file1> <file2> <directory/>
```

If the user has already staged everything intentionally, skip re-staging and verify with:
```bash
git diff --cached --stat
```

Refuse to commit if `git diff --cached --stat` is empty and there are no unpushed commits.

---

## Step 5 — Compose the commit message

Follow `branching-and-commit-conventions`. The message must:

- **Title:** `<topic> <one-line imperative summary>` ≤72 characters
- **Body:** grouped by concern — what changed, which files, why (if non-obvious)
- **Footer:** the AI-assisted commit co-author trailer per `branching-and-commit-conventions` (do not redefine a versioned string here)

Example structure:
```
Add SkillsLoader and AgentSkills.io XML inline in system prompt

Feature: skills_loader.py
- Add SkillEntryDAO (Pydantic, frozen) with name/description/file_path/disable_model_invocation
- Add SkillsLoader.load() scanning SKILLS_DIR recursively for SKILL.md frontmatter

Feature: prompts/__init__.py
- Replace SKILLS_BLOCK_TEMPLATE pointer with _format_skills_as_xml()
- Fallback to INDEX.md pointer when no skills are loaded

Tests: test_skills_loader.py
- test_skills_loader_loads_skills_from_real_skills_dir
- test_system_prompt_contains_available_skills_xml_when_skills_loaded

Co-Authored-By: Claude <noreply@anthropic.com>
```

Always show the proposed message before committing (in every mode).

---

## Step 6 — Commit

```bash
git commit -m "$(cat <<'EOF'
<title>

<body>

<footer>
EOF
)"
```

---

## Step 7 — Push to remote

### [CONFIRMATION GATE 1]

**Default (confirm-first):** Show the following and wait for explicit approval before continuing:

```
About to push branch '<branch>' to origin.

Commits to be pushed:
<git log --oneline origin/<branch>..HEAD or all commits if no upstream>

Changed files:
<git diff --stat origin/main..HEAD>

Confirm push? (yes/no)
```

**Auto mode (opt-in only):** proceed without pausing.

```bash
# First push (no upstream)
git push -u origin HEAD

# Subsequent pushes
git push
```

---

## Step 8 — Open MR / PR

### GitLab (glab)

Generate description from the commit log:
```bash
git log --oneline origin/main..HEAD
git diff origin/main..HEAD --stat
```

Create the MR:
```bash
glab mr create \
  --title "<title from commit message first line>" \
  --description "<multi-line description covering what changed and why>" \
  --target-branch main \
  --source-branch <current-branch> \
  --no-editor
```

Capture the MR URL from the output.

### GitHub (gh)

```bash
gh pr create \
  --title "<title from commit message first line>" \
  --body "<multi-line description covering what changed and why>" \
  --base main
```

Capture the PR URL from the output.

---

## Step 9 — Merge MR / PR

### [CONFIRMATION GATE 2]

**Default (confirm-first):** Show the following and wait for explicit approval before continuing:

```
About to merge:
  <MR/PR URL>
  Title: <title>
  Branch: <source> → main

Confirm merge? (yes/no)
```

**Auto mode (opt-in only):** proceed without pausing. Note: never auto-merge
unless the user explicitly opted into auto mode / asked you to merge.

### GitLab (glab)

```bash
glab mr merge --yes <MR_NUMBER>
```

If this fails (e.g. pipeline pending), try:
```bash
glab mr merge <MR_NUMBER> --squash=false --remove-source-branch=false --yes
```

### GitHub (gh)

```bash
gh pr merge --merge --yes
```

Or with squash:
```bash
gh pr merge --squash --yes
```

---

## Step 10 — Return to main and pull

```bash
git checkout main
git pull origin main
```

Confirm the latest commit is the merge commit:
```bash
git log --oneline -3
```

---

## Step 11 — Report

Print a brief summary:

```
Feature shipped.

Branch:   <feature-branch> → main
MR/PR:    <URL>
Commit:   <hash> <title>
main is now at: <latest commit hash>
```

---

## Non-Negotiables

- Never commit from `main` — stop and route to `create-feature-branch` if on main.
- Never `git add -A` or `git add .` without showing the user what will be staged.
- Never skip Gate 1 (push) or Gate 2 (merge) unless the user explicitly opted into auto mode. Confirm-first is the default.
- Always show the commit message before executing `git commit`.
- Never force-push (`--force`) unless the user explicitly requests it.
- Never amend a commit that has already been pushed.
- Eye-scan all staged content for secrets (API keys, tokens, private keys) before committing.
- If the merge fails due to conflicts, stop, report the conflict, and route into `fix-pr-review`.
