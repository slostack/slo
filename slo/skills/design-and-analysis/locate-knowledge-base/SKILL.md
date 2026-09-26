---
name: locate-knowledge-base
description: Non-blocking discovery of the project knowledge base — resolve SLO_KB_DIR
  or the default ~/.slo/KnowledgeBase/KB, find its Welcome.md / index.md entry point,
  and offer to create one when none exists.
when_to_use: Use before any step that reads or writes the knowledge base ($SLO_KB_DIR),
  and when the user asks where the knowledge base is or how to set one up.
group: design-and-analysis
kind: workflow
source_prompt: locate-knowledge-base.md
---

# Locate Knowledge Base

## Skill summary

- **Name:** `locate-knowledge-base`
- **Description:** Non-blocking discovery of the project knowledge base — resolve SLO_KB_DIR or the default ~/.slo/KnowledgeBase/KB, find its Welcome.md / index.md entry point, and offer to create one when none exists.
- **When to use:** Use before any step that reads or writes the knowledge base ($SLO_KB_DIR), and when the user asks where the knowledge base is or how to set one up.
- **Group:** `design-and-analysis`
- **Kind:** `workflow`
- **Source prompt:** `locate-knowledge-base.md`

## Examples

- A spec pre-hook says "read the KB" and `SLO_KB_DIR` is unset.
- The user asks: "Where is my knowledge base?" or "Set up a knowledge base for Slo."
- A debugging skill says "grep the KB first" on a machine that has never had one.

## Guidance

The knowledge base (KB) is optional. It improves context but is never a gate.
**Never stop, fail, or refuse the current task because no KB was found.** Every
skill that reads `$SLO_KB_DIR` defers to this procedure.

---

## Step 1 — Look for a KB

Check two places, in order. A place counts as a KB only when it is a directory
that holds an entry point: `Welcome.md`, `index.md`, `Index.md`, or (legacy
vaults) `Home.md`.

| Order | Location | Meaning |
|---|---|---|
| 1 | `$SLO_KB_DIR` | The user's explicit choice. |
| 2 | `$SLO_HOME/KnowledgeBase/KB` (`~/.slo/KnowledgeBase/KB` when `SLO_HOME` is unset) | The Slo default location. |

```bash
for dir in "${SLO_KB_DIR:-}" "${SLO_HOME:-$HOME/.slo}/KnowledgeBase/KB"; do
  [ -n "$dir" ] || continue
  for entry in Welcome.md index.md Index.md Home.md; do
    [ -f "$dir/$entry" ] && { echo "$dir/$entry"; break 2; }
  done
done
```

The first path printed is the entry point. Read it first, then follow its links
to the pages the task needs.

## Step 2 — KB found

- Use it. The caller skill continues with its own KB steps.
- If it was found only at the default location (`SLO_KB_DIR` is unset), tell the
  user once and suggest `export SLO_KB_DIR="<that directory>"` so future sessions
  load it into the system prompt.

## Step 3 — No KB found: tell the user, ask once, keep working

1. Tell the user plainly:
   - No knowledge base was found.
   - Which paths were checked, and whether `SLO_KB_DIR` is unset or points to a
     missing directory or entry point.
   - `SLO_KB_DIR` is the environment variable that points Slo at a KB.
2. Ask **once per session** whether to create one at `$SLO_HOME/KnowledgeBase/KB`
   (`~/.slo/KnowledgeBase/KB` when `SLO_HOME` is unset). Also offer the choice
   of pointing `SLO_KB_DIR` at an existing folder instead.
3. Continue the current task without the KB while the question is open. Skip
   the KB-dependent steps and say so in the output.
4. In a headless or unattended run where no one can answer, do not wait. Record
   "no knowledge base found" in the final report and continue.
5. If the user declines, do not ask again this session.

## Step 4 — Create the KB (only after the user says yes)

1. Set `SLO_HOME` if it is unset, then create the directory:
   ```bash
   [ -n "${SLO_HOME:-}" ] || export SLO_HOME="$HOME/.slo"
   export SLO_KB_DIR="$SLO_HOME/KnowledgeBase/KB"
   mkdir -p "$SLO_KB_DIR"
   ```
2. Create `Welcome.md` as the entry point, only when no entry point exists yet.
   Never overwrite an existing page.
   ```markdown
   # Welcome

   Entry point of this knowledge base. Link every top-level page from here.

   ## Sections

   - Architecture — how the systems fit together.
   - Decisions — why things are built the way they are.
   - Gotchas — failure modes and how to avoid them.
   ```
3. Persist both variables so new shells and future Slo sessions see them. Add
   them to the user's shell profile (`~/.zshrc` for zsh, otherwise `~/.bashrc`),
   and skip any line that is already there. Do not edit
   `~/.slo/shell/environment.sh`; the installer owns and rewrites it.
   ```bash
   profile="$HOME/.bashrc"; case "${SHELL:-}" in */zsh) profile="$HOME/.zshrc" ;; esac
   grep -qs '^export SLO_HOME=' "$profile" \
     || printf '\nexport SLO_HOME="${SLO_HOME:-$HOME/.slo}"\n' >> "$profile"
   grep -qs '^export SLO_KB_DIR=' "$profile" \
     || printf 'export SLO_KB_DIR="%s"\n' "$SLO_KB_DIR" >> "$profile"
   ```
4. Tell the user what was created and changed, and that Slo loads `SLO_KB_DIR`
   into its system prompt at startup, so a new shell or Slo session picks it up.
5. Return to the caller skill and use the new KB from its entry point.

## Non-Negotiables

- KB discovery is non-blocking: a missing KB never stops the task.
- Never create, move, or persist anything without the user's yes.
- Never overwrite an existing entry point or KB page.
- Ask at most once per session.
