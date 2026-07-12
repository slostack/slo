---
name: gitlab-code-test-review
description: Complete the Code-Test-Review implementation cycle while managing the GitLab issue lifecycle — pick an assigned issue, implement it with tests, open an MR, and close the issue on merge.
when_to_use: Use when the user asks to implement a GitLab issue, pick up a ticket from the backlog, or complete a coding task that is tracked as a GitLab issue moving through Todo → In-Progress → Code-Review → Closed.
group: design-and-analysis
kind: workflow
---

# Workflow: GitLab Code-Test-Review

**Type:** Pipeline
**Governs:** All feature implementation work tracked as a GitLab issue in this repository
**Extends:** [Code-Test-Review](code-test-review.md) + [GitLab Issues](../../git-ops/gitlab-issues/SKILL.md)

## Skills used in this workflow

| Step | Skill |
|---|---|
| Pre-step — Issue pickup | `skills/git-ops/gitlab-issues/SKILL.md` |
| 1 — Code + Test Loop | `skills/coding/code-test-loop/SKILL.md` |
| 2 — Code Review | `skills/design-and-analysis/review-feature-code/SKILL.md` |
| 3 — Completion Check | `skills/design-and-analysis/is-the-feature-completed/SKILL.md` |
| 4 — Create MR | `skills/git-ops/ship-feature/SKILL.md` (through MR creation), `skills/git-ops/gitlab-issues/SKILL.md` |
| 5 — Merge + close | `skills/git-ops/ship-feature/SKILL.md` (merge step), `skills/git-ops/gitlab-issues/SKILL.md` |
| Commit conventions | `skills/git-ops/branching-and-commit-conventions/SKILL.md` |

---

## When to Use

Activate this workflow whenever the operator asks to:

- "Pick up a GitLab issue and implement it"
- "Work from the backlog"
- "Implement issue #N"
- "Take the next assigned ticket"
- "Complete [task] and move it through the board"

This is the Code-Test-Review workflow with GitLab issue lifecycle management wrapped around it. Every step from Code-Test-Review remains in full force. The additions are: issue pickup before coding starts, label transitions at each gate, MR creation after completion, and issue closure on merge.

---

## GitLab Issue Workflow States

Issues move through these states in order. Never skip states unless the user explicitly instructs it.

| Label | Meaning | Transition trigger |
|---|---|---|
| `Todo` | Assigned but not started | default for new issues |
| `In-Progress` | Active implementation | pre-step: issue pickup |
| `Code-Review` | MR open, awaiting review | after MR is created |
| `Testing` | Under QA or acceptance test | optional, if user requests |
| `Released` | Deployed to an environment | explicit user request only |
| `Closed` | Done — GitLab issue state | merge completes |

Rules:
- Exactly one open-workflow label from `Todo`, `In-Progress`, `Code-Review`, `Testing` is active at any time.
- `Released` is a deployment marker, not a flow label — it may be added after closure.
- `Closed` is a GitLab state, not a label. Use `stateEvent:CLOSE` via GraphQL to close.

---

## Pre-conditions

Before the pre-step begins, confirm:

- `glab` is installed and authenticated (`glab version && glab auth status`).
- A dedicated feature branch is checked out. Never implement directly on `main`.
  - Branch naming: `<ISSUE-ID>-<short-kebab-description>` when an issue ID is available (e.g. `19-orders-backend-scaffold`), or `feature-<short-kebab-description>` when there is no issue.
- `AGENTS.md` and `docs/RESEARCH.md` have been read (or are already in context).
- The relevant KB folders have been consulted for the feature's surface area.
- All applicable `build-*.md` files for the layers this task touches have been read.
- The always-on rules are loaded: named arguments, type hints, declarative methods, method docstrings, test verification policy.

---

## Pre-Step — Issue Pickup

**GitLab skills used:** `gitlab-issues`

**What this step does:**

Identify the issue to work on, confirm it is assigned to you, and advance its label from `Todo` to `In-Progress`.

1. List your assigned issues in `Todo` state:

   ```bash
   source ~/.zshrc && glab issue list --repo <group/project> --assignee @me --label Todo
   ```

2. If the user named a specific issue (e.g. "implement issue #42"), resolve it directly:

   ```bash
   source ~/.zshrc && glab issue view 42 --repo <group/project>
   ```

3. If multiple `Todo` issues are assigned and none was named, present the list and ask the user which one to pick.

4. Confirm the issue exists, is open, and is in `Todo` state. If it is already `In-Progress`, confirm it is the same one the user wants to continue. If it is in `Code-Review` or later, ask before overriding.

5. Move the issue from `Todo` to `In-Progress`:

   ```bash
   source ~/.zshrc && glab issue update <iid> --repo <group/project> --unlabel Todo --label In-Progress
   ```

6. Verify the transition:

   ```bash
   source ~/.zshrc && glab issue view <iid> --repo <group/project>
   ```

**Output produced:**

- Issue IID and URL noted in conversation
- Issue title confirmed as the implementation target
- Issue is now labeled `In-Progress`

**Context carried forward:**
- Issue IID (used in Steps 4 and 5)
- Issue title and description (drives the implementation)
- Feature branch name

---

**[MANUAL MODE — PAUSE]**

State:

> "Issue #N is now `In-Progress`. Ready to begin Step 1 (Code + Test Loop)."

Wait for confirmation before continuing.

---

## Step 1 — Code + Test Loop

**Governing skill:** `skills/coding/code-test-loop/SKILL.md`

This step is identical to Step 1 of the [Code-Test-Review workflow](code-test-review.md). All rules apply without exception.

Implement the feature by working through each implementation unit in dependency order (migrations → domain models/DAOs → domain services → application services → routers → workers → frontend). For each unit:

1. Write the implementation unit (one function, class, route handler, migration, or component — bounded scope, single purpose).
2. Write the tests for that unit (one test per decision point).
3. Run the tests and confirm green.
4. Run the surrounding suite to confirm no regressions.
5. Only then start the next unit.

The agent must not write more than ~50 lines without running the corresponding tests.

**Coding conventions (all of them, always):**

- Named arguments on every call with 2+ arguments
- Type hints on every function signature and return type
- Google-style docstrings on all public methods
- Declarative method structure — no nested if-else, one decision per method, guard clauses at the top
- Service namespace prefixes on every `app.include_router(...)`
- Ubiquitous language — one concept, one name across every layer
- Three-file domain pattern — `model.py`, `dao.py`, `service.py`
- `invoke()` orchestration pattern for application services
- New models registered in `src/models/model.py` for Alembic

**Running tests:**

```bash
loadenv environments/test.env
PYTHONPATH=${PWD} poetry run pytest -sv tests/path/to/test_file.py::TestClass
```

After all individual units pass:

```bash
loadenv environments/test.env
PYTHONPATH=${PWD} poetry run pytest -sv tests/
```

**READY condition:** every decision point is covered by a passing test; the full suite is green; no failing tests are skipped or disabled.

---

**[MANUAL MODE — PAUSE]**

> "Step 1 complete — all tests green. Proceeding to Step 2 (Code Review) unless you would like to review the implementation first."

---

## Step 2 — Code Review

**Governing skill:** `skills/design-and-analysis/review-feature-code/SKILL.md`

This step is identical to Step 2 of the [Code-Test-Review workflow](code-test-review.md). All rules apply without exception.

Conduct a structured review of the Step 1 implementation against the issue description and any linked specification:

1. Extract all requirements as a checklist from the issue / spec.
2. Inventory every implementation file by layer.
3. Map each requirement to its implementation (Covered / Partial / Not Covered).
4. Trace the end-to-end flow — no dead code, no disconnected workers, no unregistered queues.
5. Analyze test coverage — untested files, missing decision branches, missing error paths.
6. Check compliance against all applicable coding conventions.
7. Compile findings: Glaring Gaps (must fix), Nice-to-Haves, Temporary Shortcuts.

If Glaring Gaps are found, return to Step 1 before the review is complete.

**READY condition:** review report is complete; no Glaring Gaps remain.

---

**[MANUAL MODE — PAUSE]**

> "Step 2 complete — code review report ready. [N glaring gaps / no glaring gaps]. Proceeding to Step 3 (Completion Check)."

---

## Step 3 — Completion Check

**Governing skill:** `skills/design-and-analysis/is-the-feature-completed/SKILL.md`

This step is identical to Step 3 of the [Code-Test-Review workflow](code-test-review.md). All rules apply without exception.

Run a fresh codebase scan against the full set of expected deliverables:

1. Re-derive the deliverable checklist from the issue / spec by layer.
2. Search the codebase for evidence of each deliverable.
3. Score each: Done, Partial, Not Started.
4. Calculate completion percentage.
5. For any Not Started or Partial items, produce a specific implementation guide.
6. If multiple items remain, produce a dependency graph for the remaining work.

If completion is below 100%, return to Step 1 and implement the missing items.

**READY condition:** 100% of deliverables are implemented and all tests remain green. (Or operator explicitly accepts deferral.)

---

**[MANUAL MODE — PAUSE]**

> "Step 3 complete — [X]% complete. [Workflow proceeding to Step 4 / N items remain — returning to Step 1.]"

---

## Step 4 — Create MR and Advance to Code-Review

**GitLab skills used:** `ship-feature` (Steps 1–8 only — up to and including MR creation; not merge), `gitlab-issues`

**What this step does:**

Open the MR for the completed feature branch and move the GitLab issue from `In-Progress` to `Code-Review`.

### 4a — Detect platform and verify auth

```bash
git remote get-url origin
source ~/.zshrc && glab version && glab auth status
```

### 4b — Stage and commit

Stage only the files relevant to the feature. Never use `git add -A` blindly.

```bash
git add <file1> <file2> <directory/>
git diff --cached --stat
```

Eye-scan staged content for secrets (API keys, tokens, private keys, bcrypt hashes) before committing.

Compose the commit message following `branching-and-commit-conventions`:

```
<ISSUE-ID> <one-line imperative summary>

- What changed and why (grouped by concern)
- Files modified or created

Co-Authored-By: Claude <noreply@anthropic.com>
```

Always show the proposed commit message before running `git commit`. Seek confirmation.

```bash
git commit -m "$(cat <<'EOF'
<title>

<body>

<footer>
EOF
)"
```

### 4c — Push branch

```bash
git push -u origin HEAD
```

### 4d — Open MR

```bash
source ~/.zshrc && glab mr create \
  --title "<issue-id> <title from commit message>" \
  --description "<multi-line description: what was implemented, which files, test coverage, link to issue>" \
  --target-branch main \
  --source-branch <current-branch> \
  --no-editor
```

Capture the MR URL.

### 4e — Advance issue label

Move the issue from `In-Progress` to `Code-Review`:

```bash
source ~/.zshrc && glab issue update <iid> --repo <group/project> --unlabel In-Progress --label Code-Review
```

Verify:

```bash
source ~/.zshrc && glab issue view <iid> --repo <group/project>
```

**Output produced:**

- MR URL
- Issue is now labeled `Code-Review`

---

**[PAUSE — MANDATORY before Step 5]**

This gate is mandatory in both auto and manual mode.

Present:

> "Step 4 complete.
>
> MR: <URL>
> Issue #N is now `Code-Review`.
>
> Awaiting review and your instruction to merge. When you are ready, say 'merge' or 'ship it'."

Do **not** proceed to Step 5 without an explicit merge instruction from the operator.

---

## Step 5 — Merge MR and Close Issue

**Triggered by:** explicit operator instruction to merge ("merge", "ship it", "land it", "merge the MR")

**GitLab skills used:** `ship-feature` (Step 9–10), `gitlab-issues`

**What this step does:**

Merge the MR, return to main, and close the GitLab issue.

### 5a — Merge MR

```bash
source ~/.zshrc && glab mr merge --yes <MR_NUMBER>
```

If the merge fails due to a pending pipeline or conflicts:

```bash
source ~/.zshrc && glab mr merge <MR_NUMBER> --squash=false --remove-source-branch=false --yes
```

If there are merge conflicts, stop immediately, report the conflict, and ask the user how to proceed. Do not force-merge.

### 5b — Return to main and pull

```bash
git checkout main
git pull origin main
git log --oneline -3
```

Confirm the latest commit is the merge commit.

### 5c — Close the issue

Use the GraphQL mutation to transition the issue to `Closed` state:

```bash
source ~/.zshrc && glab api graphql -f query='mutation {
  workItemUpdate(input:{
    id:"gid://gitlab/WorkItem/<GLOBAL_ID>",
    stateEvent:CLOSE
  }) {
    workItem { iid state webUrl }
    errors
  }
}'
```

To get the global ID if not already known:

```bash
source ~/.zshrc && glab api graphql -f query='{ project(fullPath: "<group/project>") { workItem(iid: "<iid>") { id iid state } } }'
```

### 5d — Released label (conditional)

Apply only when the user explicitly asks ("mark it as released", "move to Released", "it's deployed"):

```bash
source ~/.zshrc && glab issue update <iid> --repo <group/project> --label Released
```

`Released` does not reopen the issue — it is a deployment marker added after closure.

**Output produced:**

- Merge commit hash on `main`
- Issue is `Closed` (GitLab state)
- Issue carries `Released` label if user requested it

---

## Exit Condition

The GitLab Code-Test-Review Workflow is complete when:

- **Pre-Step:** Issue is `In-Progress`, feature branch is checked out.
- **Step 1:** All implementation units written, all tests pass, full suite green.
- **Step 2:** Code review report complete, no Glaring Gaps remain.
- **Step 3:** Completion assessment at 100%, all tests green.
- **Step 4:** MR is open, issue is `Code-Review`.
- **Step 5:** MR is merged, `main` is updated, issue is `Closed` (and `Released` if requested).

---

## What Does Not Change

The following rules remain in effect throughout this entire workflow:

- The code+test cadence is non-negotiable. Write a unit, test it, run it green, then proceed.
- All always-on coding conventions from `CLAUDE.md` apply to every line of code written.
- Secret scanning before every commit — eye-scan all staged content for API keys, tokens, bcrypt hashes, and private keys.
- **Confirmation before commit, push, or PR** — never commit, push, or create an MR without showing the operator the commit message and awaiting explicit approval.
- **Step 5 is always gated** — never merge or close an issue without an explicit operator instruction, even in auto mode.
- `glab` commands require `source ~/.zshrc &&` prefix because `GITLAB_TOKEN` is set there.
- Never use `git add -A` or `git add .` blindly — always stage by explicit path and verify with `git diff --cached --stat`.

---

## Quick Reference

```
Trigger: "implement issue #N" / "pick up the next ticket" / "work on [issue]"

Pre-conditions: glab auth OK, feature branch checked out,
                AGENTS.md and docs/RESEARCH.md loaded, build-*.md for task layers loaded

Pre-Step: Find assigned Todo issue → move to In-Progress

Step 1: Code + Test Loop (write unit → test → green → repeat)
        └─ Output: all files written, full suite green

Step 2: Code Review (completeness, flow, test coverage, conventions)
        └─ Output: review report; return to Step 1 if Glaring Gaps

Step 3: Completion Check (fresh scan; percentage score)
        └─ Output: completion assessment; return to Step 1 if incomplete

Step 4: Create MR + move issue to Code-Review
        └─ Output: MR URL, issue is Code-Review
        └─ [MANDATORY GATE — await merge instruction]

Step 5: Merge MR + Close issue (triggered by operator)
        └─ Output: main updated, issue Closed (+ Released if requested)

Label transitions:
  Todo → In-Progress  (pre-step)
  In-Progress → Code-Review  (step 4)
  Code-Review → Closed  (step 5)
  Closed + Released  (step 5, if user requests)
```
