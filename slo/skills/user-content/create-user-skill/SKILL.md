---
name: create-user-skill
description: Guide the user through creating a new personal skill stored at
  ~/.slo/user_skills. Gathers intent, drafts YAML frontmatter and guidance body,
  confirms with the user, and writes the SKILL.md file to the correct location.
when_to_use: Use when the user asks to create a new custom skill, save a convention
  as a skill, add a personal skill to their Slo library, or capture a repeatable
  pattern as a reusable prompt.
group: user-content
kind: skill
---

# Create User Skill

## Skill summary

- **Name:** `create-user-skill`
- **Description:** Guide the user through creating a new personal skill stored
  at `~/.slo/user_skills`.
- **When to use:** Use when the user asks to create a new custom skill, save a
  convention, or add a personal skill to their Slo library.
- **Group:** `user-content`
- **Kind:** `skill`

## Examples

- The user asks: "Create a skill for writing PR descriptions in our team's format."
- The user asks: "Save this pattern as a custom skill."
- The user asks: "I want to add a personal skill for structuring commit messages."
- The user says: "Can you help me make a reusable skill for code-review checklists?"

## Guidance

When this skill is invoked, execute the following steps in order. Do not skip steps.
Confirm with the user at Step 5 before writing anything to disk.

---

### Step 1 — Gather intent

Ask the user these questions (you may ask them together):

1. **Task coverage:** "What task or convention does this skill cover? Describe it in
   one or two sentences."
2. **Trigger condition:** "When should I automatically use this skill? What phrase or
   situation should activate it?"
3. **Guidance content:** "What are the key steps, rules, or conventions it should
   encode? You can describe them conversationally and I'll format them."

If the user has already provided this information in their initial request, do not
re-ask — proceed to Step 2.

---

### Step 2 — Derive the slug

Convert the task description to a kebab-case slug:

- Use lowercase letters and hyphens only.
- Keep it short (2-4 words).
- Make it descriptive, not generic.

Examples:
- "write PR descriptions for our team" → `team-pr-descriptions`
- "structure commit messages" → `commit-message-structure`
- "Alembic migration notes" → `migration-notes`

State the derived slug to the user: "I'll use the name `<slug>` for this skill."

---

### Step 3 — Draft the YAML frontmatter

Construct the frontmatter block. Use the gathered intent to fill in each field:

```yaml
---
name: <slug>
description: <One-line description of what the skill does. Used in the available
  skills manifest. Be specific — the model matches this against the user's task.>
when_to_use: Use when <specific trigger condition derived from Step 1>.
group: user
kind: skill
---
```

Rules:
- `name` must be kebab-case and match the slug from Step 2.
- `description` must fit on one line (or two lines with a YAML continuation indent).
- `when_to_use` must be a natural language sentence starting with "Use when …".
- `group` should be `user` for personal skills.
- `kind` must be `skill`.

---

### Step 4 — Draft the guidance body

Structure the body using this template. Adapt section content to the user's skill,
but keep the structure consistent with vendored skills so the agent can navigate
user skills the same way it navigates vendored ones.

```markdown
# <Skill Title (Title Case of the slug)>

## Skill summary

- **Name:** `<slug>`
- **Description:** <repeat description from frontmatter>
- **When to use:** <repeat when_to_use from frontmatter>
- **Group:** `user`
- **Kind:** `skill`

## Examples

- <Concrete trigger phrase 1>
- <Concrete trigger phrase 2>
- <Concrete trigger phrase 3>

## Guidance

<The substantive content. Write this as a step-by-step guide or a set of rules
the agent must follow when executing this skill. Use numbered steps, code blocks,
and examples liberally. The goal is that the agent can implement the convention
correctly on the first attempt without asking follow-up questions.>
```

Write the guidance content in the agent's voice (second person, declarative, present
tense): "When asked to X, do Y. Always Z. Never Q."

Be thorough — a skill that is too sparse will not constrain the agent's behavior. Aim
for at least 200 words of guidance content.

---

### Step 5 — Confirm with the user

Show the complete drafted SKILL.md (frontmatter + body) to the user. Say:

> "Here is the draft for your new skill. Does this look correct? Any changes before I
> save it?"

Wait for the user's response. Apply any requested changes and show the updated draft.
Do not write the file until the user explicitly approves ("looks good", "yes", "save
it", etc.).

---

### Step 6 — Write the file

Once the user approves, use the `write` tool to save the file:

```
path: ~/.slo/user_skills/<slug>/SKILL.md
content: <full SKILL.md including frontmatter and body>
```

The `write` tool creates parent directories automatically. Do not create the directory
separately.

---

### Step 7 — Confirm success

After the write tool completes, tell the user:

> "Your new skill `<slug>` has been saved to `~/.slo/user_skills/<slug>/SKILL.md`.
> It will appear in your available skills on the next Slo session. If you want to
> use it in this session, start a new session with `/new`."

---

### Override awareness

If the slug matches a vendored skill name (e.g. `build-routers`), warn the user before
Step 5:

> "⚠️ The name `<slug>` matches a built-in Slo skill. Your version will override the
> built-in one in all future sessions. This is intentional if you want to customize
> that skill for your workflow. Proceed?"

---

### Editing an existing user skill

If the user asks to edit or update an existing user skill:

1. Read `~/.slo/user_skills/<slug>/SKILL.md` with the `read` tool.
2. Apply the requested changes.
3. Show the updated draft to the user (Step 5).
4. Overwrite the file with the `write` tool (Step 6).
5. Confirm (Step 7) — "Your skill `<slug>` has been updated."
