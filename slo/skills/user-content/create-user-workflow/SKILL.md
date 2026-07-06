---
name: create-user-workflow
description: Guide the user through creating a new personal workflow stored at
  ~/.slo/user_workflows. Workflows are pipeline SKILL.md files with When to Use,
  Pre-conditions, and numbered Steps sections. The agent gathers intent, drafts
  the pipeline structure, confirms, and writes the file.
when_to_use: Use when the user asks to create a custom workflow, codify a multi-step
  process, save a pipeline as a reusable workflow, or build a personal automation
  sequence for recurring tasks.
group: user-content
kind: skill
---

# Create User Workflow

## Skill summary

- **Name:** `create-user-workflow`
- **Description:** Guide the user through creating a new personal workflow stored
  at `~/.slo/user_workflows`.
- **When to use:** Use when the user asks to create a custom workflow, codify a
  multi-step process, or save a pipeline as a reusable workflow.
- **Group:** `user-content`
- **Kind:** `skill`

## Examples

- The user asks: "Create a workflow for our team's weekly release process."
- The user asks: "Save this multi-step process as a reusable workflow."
- The user asks: "I want a workflow that takes me from a Jira ticket to a deployed feature."
- The user says: "Can you help me build a personal code-review workflow?"

## Guidance

When this skill is invoked, execute the following steps in order. A workflow is a
**pipeline** — a sequence of governed steps that the agent executes in order, each
producing a defined output that feeds the next. Do not skip steps. Confirm with the
user at Step 5 before writing anything to disk.

---

### Step 1 — Gather intent

Ask the user these questions (you may ask them together):

1. **Pipeline purpose:** "What is the end goal of this workflow? What problem does it
   solve or what process does it automate?"
2. **Trigger:** "When should this workflow activate? What phrase or situation should
   cause you to start it?"
3. **Steps:** "Walk me through the steps at a high level. What happens first? What
   comes next? What is the final deliverable?"
4. **Inputs:** "What does the workflow need to start? (e.g. a JIRA ticket, a feature
   description, a repo URL)"
5. **Exit condition:** "How do you know the workflow is done? What does 'done' look
   like?"

If the user has already described the workflow, extract these answers from their
description rather than re-asking.

---

### Step 2 — Derive the name

Convert the workflow purpose to a kebab-case name:
- 2-4 words, lowercase, hyphens only.
- Make it describe the pipeline's output, not just its input.

Examples:
- "weekly release process" → `weekly-release`
- "Jira ticket to deployed feature" → `ticket-to-deploy`
- "code review process" → `code-review-process`

State the derived name: "I'll use the name `<name>` for this workflow."

---

### Step 3 — Draft the YAML frontmatter

```yaml
---
name: <name>
description: <One-line pipeline description. State what the workflow produces
  or achieves. Used in the available skills manifest.>
when_to_use: Use when <specific trigger derived from Step 1>.
group: user
kind: workflow
---
```

Rules:
- `kind` must be `workflow` (not `skill`).
- `description` must clearly convey the pipeline's purpose.
- `when_to_use` must name the trigger condition precisely.

---

### Step 4 — Draft the pipeline body

Structure the body using this template. This mirrors the format used by vendored
workflows (e.g. `skills/design-and-analysis/workflows/specification-development.md`):

```markdown
# Workflow: <Title (Title Case)>

**Type:** Pipeline
**Governs:** <What this workflow governs — e.g. "All release work for project X">

---

## When to Use

Activate this workflow whenever:

- <Trigger phrase 1>
- <Trigger phrase 2>
- <Trigger phrase 3>

---

## Pre-conditions

Before the first step begins, confirm:

- <Required input or context that must exist>
- <Pre-loaded files, tickets, or state the workflow needs>

---

## Steps

### Step 1 — <Step Name>

**Input consumed:** <What this step takes as input>

**What this step does:**
<Detailed description of what the agent must do in this step. Be concrete —
name tools to use, decisions to make, and outputs to produce.>

**Output produced:**
<What this step produces — a document, a list, a code change, etc.>

**READY condition:** <How to know this step is complete>

---

[Repeat for each step]

---

## Exit Condition

The workflow is complete when:

- <Final state that indicates all work is done>

---

## What Does Not Change

<List any rules or conventions that remain in force throughout — things the workflow
does not override.>
```

Work with the user to fill in each section. Ask clarifying questions for any step that
is vague. The goal is a workflow body detailed enough that the agent can execute it
without follow-up questions.

---

### Step 5 — Confirm with the user

Show the complete drafted workflow SKILL.md (frontmatter + body) to the user. Say:

> "Here is the draft for your new workflow. Does this look correct? Any changes before
> I save it?"

Wait for the user's response. Apply any requested changes. Do not write the file until
the user explicitly approves.

---

### Step 6 — Write the file

Once approved, use the `write` tool:

```
path: ~/.slo/user_workflows/<name>/SKILL.md
content: <full SKILL.md>
```

---

### Step 7 — Confirm success

> "Your new workflow `<name>` has been saved to `~/.slo/user_workflows/<name>/SKILL.md`.
> It will appear in your available skills on the next Slo session. Start a new session
> with `/new` to use it immediately."

---

### Override awareness

If the name matches a vendored workflow or skill name, warn before Step 5:

> "⚠️ The name `<name>` matches a built-in Slo skill or workflow. Your version will
> override it in all future sessions. Proceed?"

---

### Editing an existing user workflow

1. Read `~/.slo/user_workflows/<name>/SKILL.md` with the `read` tool.
2. Apply requested changes.
3. Show the updated draft (Step 5).
4. Overwrite with the `write` tool (Step 6).
5. Confirm: "Your workflow `<name>` has been updated."
