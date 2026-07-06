---
name: gitlab-issues
description: Publish specification files to GitLab Issues with full-fidelity
  descriptions, link child issues to an overview issue, and manage workflow
  labels plus open/closed state safely with glab.
when_to_use: Use when the user asks to create, refresh, link, close, relabel,
  or convert GitLab Issues from specification files, planning docs, or other
  repo-authored execution documents.
group: git-ops
kind: workflow
source_prompt: publish-and-manage-issues-gitlab.md
---

# GitLab Issues

## Skill summary

- **Name:** `gitlab-issues`
- **Description:** Publish specification files to GitLab Issues with full-fidelity descriptions, link child issues to an overview issue, and manage workflow labels plus open/closed state safely with glab.
- **When to use:** Use when the user asks to create, refresh, link, close, relabel, or convert GitLab Issues from specification files, planning docs, or other repo-authored execution documents.
- **Group:** `git-ops`
- **Kind:** `workflow`
- **Source prompt:** `publish-and-manage-issues-gitlab.md`

## Examples

- "Publish this spec folder as GitLab Issues."
- "Create an overview issue and link all child spec issues to it."
- "Refresh these issues with the latest full spec text and close the completed ones."
- "Convert these GitLab tasks into issues and keep the state accurate."
- "Create the issues with Todo, then move them through In-Progress, Code-Review, Testing, and Released."

## Guidance

## Goal

Turn local specification files into **developer-ready GitLab Issues** without
losing any source detail.

GitLab implements issues as a work-item type, so this skill still uses
`glab work-items` plus GraphQL work-item mutations where needed. The required
created type is **issue**, not **task**.

The default posture of this skill is:

- publish the **full text**,
- normalize machine-specific paths,
- create the overview issue first,
- label every newly created issue `Todo`,
- link the remaining issues to the overview,
- move open issues through `In-Progress`, `Code-Review`, and `Testing` as work advances,
- close issues only after implementation, code review, and testing are complete,
- add `Released` when the feature is pushed to production or another desired environment,
- leave unfinished issues **Open**,
- convert any mistakenly created tasks into issues.

## Non-Negotiables

- Never truncate the source text.
- Never replace a spec with a summary when the issue is meant to guide implementation.
- Never create a GitLab task when the execution artifact should be an issue.
- Never leave local absolute paths in the published description.
- Never leave a newly created issue without the `Todo` label.
- Never keep multiple active workflow labels from `Todo`, `In-Progress`, `Code-Review`, `Testing` on the same open issue.
- Never treat `Closed` as a label; it is the GitLab issue state.
- Never create orphan child issues when the spec set has an overview issue.
- Never close an item unless the user explicitly marked it done or the workflow clearly establishes that it is done.
- Never assume `glab work-items update` can do everything directly — use GraphQL when linking or state mutation needs it.
- Never leave parallel task+issue duplicates active after a conversion unless the user explicitly asks for that.

## Workflow

### 1. Verify `glab`

Confirm:

```bash
glab version
glab auth status
```

If auth is broken, stop and ask the user to fix `glab auth login`.

### 2. Inventory the publish set

List the spec directory and identify the files that become issues.

Typical publish set:

- `00-overview.md`
- numbered child slices
- `90-verification-report.md`
- `91-task-breakdown.md`

Do not publish helper files like `TODO.md` unless the user asked for them.

### 3. Derive stack-aware titles

Use titles that identify the implementation surface clearly.

Pattern:

```text
[stack][sub-app][frontend] NN.XX Title | Optional subtitle
```

Examples:

```text
[backend][orders_service] 19.03 Orders Backend Scaffold, Namespace, And Datastores
[web][admin_ui] 20.04 Order List, Search, Sidebar, And Shared UI
[deployment][backend][web][orders_service] 20.09 Deployment, Launch Configs, Doc Sync, And Verification
```

### 4. Build the full description

For every item:

1. read the source file,
2. normalize local paths,
3. prepend a short publishing note,
4. publish the **full resulting markdown**.

Recommended note:

```markdown
> **Publishing note:** This issue contains the full specification text with no truncation.
> Absolute local filesystem paths were normalized to repo-relative paths.
> References to external sibling repos remain identified as external references.
```

### 5. Normalize non-portable paths

Apply these rules before publishing:

- Convert repo-local absolute paths to repo-relative paths.
- Convert absolute sibling-reference paths (for example `orders-docs/...`) to a portable relative/reference form.
- If a path points outside the current repo, explicitly note that it is an external sibling reference.

### 6. Create issues

Use:

```bash
glab work-items create --repo <group/project> --type issue --title "..." --description "..." -F json
```

Capture:

- global ID
- IID
- title
- state
- URL

Create the overview issue first.

Immediately label every newly created issue `Todo`:

```bash
glab issue update <iid> --repo <group/project> --label Todo
```

### 7. Link children to overview

Use GraphQL mutation `workItemAddLinkedItems`.

Example shape:

```bash
glab api graphql -f query='mutation {
  workItemAddLinkedItems(input:{
    id:"gid://gitlab/WorkItem/<OVERVIEW_ID>",
    workItemsIds:["gid://gitlab/WorkItem/<CHILD_ID>"]
  }) {
    message
    errors
    workItem { iid webUrl }
  }
}'
```

Important:

- maximum 10 linked ids per mutation call
- chunk larger sets
- default related-link semantics are fine unless the user requests a stricter hierarchy model

### 8. Manage workflow labels and closed state

Workflow labels:

- `Todo` — default for every new issue
- `In-Progress` — active implementation
- `Code-Review` — implementation complete and under review
- `Testing` — feature under test
- `Released` — feature pushed to production or another desired environment

Rules:

- Keep exactly one active open-workflow label from `Todo`, `In-Progress`, `Code-Review`, `Testing`.
- `Released` is a deployment marker and may be added after closure.
- `Closed` is the GitLab issue state, not a label.

Examples:

```bash
glab issue update <iid> --repo <group/project> --unlabel Todo --label In-Progress
glab issue update <iid> --repo <group/project> --unlabel In-Progress --label Code-Review
glab issue update <iid> --repo <group/project> --unlabel Code-Review --label Testing
glab issue update <iid> --repo <group/project> --unlabel Testing --label Released
```

To close a done issue, use GraphQL mutation `workItemUpdate` with `stateEvent:CLOSE`.

```bash
glab api graphql -f query='mutation {
  workItemUpdate(input:{
    id:"gid://gitlab/WorkItem/<ID>",
    stateEvent:CLOSE
  }) {
    workItem { iid state webUrl }
    errors
  }
}'
```

To reopen:

```text
stateEvent:REOPEN
```

### 9. Convert a task into an issue when needed

If an item was mistakenly published as a GitLab task:

1. read the task title, description, and state,
2. create a replacement with `--type issue`,
3. relink it to the correct overview issue,
4. restore the correct open/closed state,
5. remove the superseded task.

### 10. Verify the publish

Check:

- titles match the intended stack surface
- description length looks consistent with source size
- no absolute local paths remain
- overview issue exists
- child issues are linked
- every new issue carries `Todo` unless intentionally advanced
- no issue has conflicting open-workflow labels
- done/open state matches the user instruction
- released issues carry `Released` when requested
- no accidental GitLab tasks remain for the published spec set

Useful commands:

```bash
glab work-items list --repo <repo> -F json
glab api graphql -f query='<verification query>'
```

## Output format

Return a concise publish report with:

1. overview issue
2. child issues created/updated
3. workflow labels applied or changed
4. issues closed as done
5. issues left open
6. normalization actions applied
7. task-to-issue conversions performed

Example:

```text
Published Step 20 issues.

Overview:
- #38 [web][backend][orders_service][deployment] 20.00 Overview | ...

Workflow labels:
- #38 Todo
- #43 In-Progress
- #47 Released

Closed:
- #39 20.01 ...
- #40 20.02 ...

Open:
- #43 20.05 ...
- #44 20.06 ...

Normalization applied:
- repo-local absolute paths rewritten to repo-relative paths
- orders-docs paths marked as external sibling references

Converted:
- replaced task #14 with issue #38
```
