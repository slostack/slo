---
name: distill-learnings
description: 'End-of-implementation: capture non-obvious solutions and patterns to
  LEARNINGS.md.'
when_to_use: Use at the close of a session where something hard was figured out.
group: design-and-analysis
kind: workflow
source_prompt: distill-learnings.md
---

# Distill Learnings

## Skill summary

- **Name:** `distill-learnings`
- **Description:** End-of-implementation: capture non-obvious solutions and patterns to LEARNINGS.md.
- **When to use:** Use at the close of a session where something hard was figured out.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `distill-learnings.md`

## Examples

- The user asks for an end-to-end workflow that fits: End-of-implementation: capture non-obvious solutions and patterns to LEARNINGS.md.
- Use at the close of a session where something hard was figured out.

## Guidance

> After completing a non-trivial implementation task, distill the key insights into `<workspace>/LEARNINGS.md` so future conversations don't re-discover the same solutions from scratch.

---

## Purpose

Every multi-turn implementation session produces insights that are not obvious from reading the code alone — workarounds for tooling quirks, architectural decisions that were tried and rejected, surprising constraints discovered mid-flight, and **bugs that took real effort to diagnose**. These insights decay the moment the conversation ends.

`LEARNINGS.md` is the shared memory across all repositories in the workspace. It captures **solutions to recurring problems** and **bug resolutions** so agents working in any repo can consult it before solving a problem that has already been solved.

---

## When to Distill

Distill a learning when any of the following occur during the current session:

| Trigger | Example |
|---------|---------|
| A problem took multiple attempts to solve | Docker networking issue required `external: true` on the network |
| A workaround was needed for a tool or library limitation | SQLAlchemy async driver requires `expire_on_commit=False` |
| An architectural decision was made after evaluating alternatives | Chose SQLite over Redis for persistence because the app runs on the host, not in Docker |
| A non-obvious constraint was discovered | `pipx install` requires `package-mode = true` in pyproject.toml |
| A pattern was established that future work should follow | Per-service FIFO queues with tag pinning to prevent race conditions |
| A debugging technique proved effective | Use `docker compose ps --format json` for machine-parseable container state |
| A bug took significant effort to diagnose | `apt-get` hangs in scripts because `tzdata` prompts interactively — fix with `DEBIAN_FRONTEND=noninteractive` |
| An error message was misleading or non-obvious | `MissingGreenlet` actually means you accessed an expired SQLAlchemy attribute after commit |
| A fix required understanding a tool's internal behavior | `docker compose ps` returns different JSON formats depending on Docker version |
| A race condition or timing issue was found and fixed | Subprocess env vars not inherited when dashboard started without `loadenv` |
| A platform-specific gotcha was discovered | `$USER` is unset in bare Docker containers — use `${USER:-$(id -un)}` |

### Bug Solutions Are First-Class Learnings

When you fix a bug during a session, record it if any of these apply:

- **The error message didn't point to the root cause** — document the real cause so the next agent doesn't waste turns chasing the misleading message
- **The fix required trying multiple approaches** — record what didn't work and what did, so the next agent goes straight to the solution
- **The bug was environment-specific** — bare containers, CI runners, different OS, ARM vs x86 — these recur every time someone sets up a new environment
- **The bug involved timing or ordering** — startup sequences, async operations, subprocess spawning — these are invisible in static code review

Use the same learning format but be specific about the **error message or symptom** and the **exact fix**:

```markdown
### [Bug title — include the error message or symptom]

**Context:** [What you were doing when this broke]

**Symptom:** [The exact error message or observable failure — copy-paste the key line]

**Root cause:** [The actual problem, which is often different from what the error suggests]

**Fix:** [The specific change that resolved it — be concrete enough to apply directly]
```

**Do NOT distill:**
- Code patterns already captured in other code prompts (e.g., domain 3-file pattern, router conventions)
- Trivial typo fixes or one-line import corrections that are unlikely to recur
- Information that can be derived by reading the code or git history

---

## LEARNINGS.md Format

The file lives at `<workspace>/LEARNINGS.md` (next to the `.code-workspace` file). It is organized by topic, not by date or conversation. Each learning follows this structure:

```markdown
### [Short descriptive title]

**Context:** [What problem was being solved — 1-2 sentences]

**Insight:** [The non-obvious solution or decision — be specific enough that an agent can act on this without further research]

**Why it matters:** [What goes wrong if you don't know this — the failure mode]
```

### Organization Rules

1. **Group by topic** using H2 headers (e.g., `## Docker & Container Management`, `## SQLAlchemy & Database`, `## Packaging & Distribution`)
2. **Keep each learning to 3-6 lines** — this is a reference, not a narrative
3. **Use the imperative mood** in the insight — tell the reader what to do
4. **Include the failure mode** — knowing what breaks makes the insight actionable
5. **Deduplicate** — before adding a new learning, check if an existing entry covers it. Update the existing entry if it does.
6. **Prune** — if a learning is no longer relevant (e.g., the library was upgraded, the workaround was fixed upstream), remove it

---

## How to Distill

At the end of a significant implementation session, follow these steps:

1. **Read** `<workspace>/LEARNINGS.md` to understand what's already recorded
2. **Reflect** on the current session — what was non-obvious? What would you tell your future self?
3. **Draft** 1-3 learnings using the format above
4. **Place** each learning under the appropriate H2 topic section (create a new section if none fits)
5. **Write** the updated file

---

## How to Consult Learnings

Before starting a non-trivial task, read `LEARNINGS.md` and check if any existing insights apply to the current problem domain. This is especially important for:

- Docker and container orchestration tasks
- Database migration and persistence work
- Packaging, distribution, and deployment
- Cross-service communication patterns
- Testing infrastructure and CI/CD

### When you're stuck

If you hit an error you can't explain, a hang with no output, or a fix that doesn't work — **stop and re-read `LEARNINGS.md` before trying another approach.** Many entries were written after exactly this kind of dead end. Scan the topic section that matches your problem domain and look for entries whose **Symptom** or **Why it matters** line matches what you're seeing. The answer may already be there.

This is especially true for:
- Misleading error messages (the real cause is documented, not the symptom)
- Silent failures (hangs, empty output, commands that "succeed" but do nothing)
- Environment-specific bugs (works locally, breaks in Docker / CI / ARM)
- Ordering and timing issues (startup sequences, async races, subprocess inheritance)

If a learning applies, follow its guidance. If a learning turns out to be wrong or outdated, update or remove it.

---

## Quick Reference

| What | Where |
|------|-------|
| Learnings file | `<workspace>/LEARNINGS.md` |
| This prompt | `skills/design-and-analysis/distill-learnings/SKILL.md` |
| When to write | After completing a non-trivial implementation with reusable insights |
| When to read | Before starting work in any repo — check for applicable insights |
| Format | Context / Insight / Why it matters — 3-6 lines per entry |
| Organization | By topic (H2 headers), not by date |
