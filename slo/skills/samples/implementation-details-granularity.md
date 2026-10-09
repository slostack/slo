# Sample: Granular Implementation Details for a Technical Sub-Spec

This packaged sample demonstrates the required depth for `## 7. Implementation Details`.
It is intentionally concrete: the implementing agent can identify the owning files and
symbols, make the change in the required order, preserve stated behavior, and write the
specific tests that prove it. It is a **shape and granularity example**, not a directive to
introduce these exact modules into another application.

> **NOTE**
>
> The samples are independent files and their file path is denoted in the comments

-----

## Overview Sample

> **Path**
> <feature-specifications-root>/20-system-prompt-analysis-and-pi-parity/00-overview.md

# 19.a — System Prompt Pi Parity: Parent Overview

**Status:** proposed
**Owner:** unassigned
**Last updated:** 2026-06-13
**Parent spec:** `../18-system-prompt-analysis-and-pi-parity.md`
**Branch:** `feature-system-prompt-pi-parity`
**Repo:** `slo/`
**Approx. size:** L
**Artifact:** Standalone engineering sub-spec, accompanied by its required product overview

---

## 1. Context

### Changes

This feature closes five gaps between Slo's runtime system prompt and Pi's. Two are outright bugs (the prompt always says the agent has no tools; the tool-use guidelines block never fires). Three are structural divergences (skills are pointer-based rather than inlined XML; there is no user-global context tier; there is no self-documentation block). Together they produce a prompt that is materially weaker than Pi's: the model cannot accurately describe what it can do, never receives file-exploration guidance, and may skip the entire skill system because the skill index file is never read.

The feature is divided into five dependency-ordered sub-specs, described in full below.

### Big Picture

Slo's system prompt is assembled at agent construction time inside `SloAgent.__init__` by calling `SystemPromptBuilder.invoke()`. That call is the single seam through which all five gaps flow. B1 and B2 both trace back to the same root cause: `SloAgent.__init__` calls `build_slo_agent(tools=tools)` where `tools` is `None` in every normal session (the default value), which causes `build_slo_agent` to resolve the 9-tool extended bundle internally — but `__init__` then passes the original `None` forward to `_resolve_system_prompt`, so `SystemPromptBuilder` receives an empty sequence and emits `(none)` for the tools block. The three structural gaps (D1, D4, D6) each require their own dedicated change: skills discovery must run at prompt assembly time and inline XML, context discovery must grow a user-global tier, and a self-documentation block must be authored and wired in.

Downstream, everything the sub-specs change flows through `_build_initial_messages`, which prepends the system prompt as a `SystemMessage` on every turn. Prompt-cache economics for Anthropic (and, by extension, cost-sensitivity for OpenAI) mean that the order of stable vs. session-specific sections in the assembled prompt is load-bearing — this overview captures that reasoning so the sub-spec authors do not duplicate it.

### Existing structure we are extending

```
slo/src/agents/slo_agent/
    agent.py                        # SloAgent.__init__, _resolve_system_prompt
    graph.py                        # build_slo_agent — resolves tools=None to extended bundle
    project_context.py              # ProjectContextDiscovery — walks cwd→.git, no user tier
    prompts/
        __init__.py                 # SystemPromptBuilder.invoke — assembles all sections
        system_prompt.py            # ROLE_LINE, SKILLS_BLOCK_TEMPLATE, KB_BLOCK, et al.

slo/src/agents/tools/
    bundles.py                      # create_extended_tools → 9 tools
    prompt_snippets.py              # TOOL_PROMPT_SNIPPETS registry
    bash.py / grep.py / …           # per-tool BASH_PROMPT_SNIPPET etc.

slo/skills/
    INDEX.md                        # current pointer target — to be superseded by XML inlining
    coding/
    git-ops/
    design-and-analysis/
    tui/
    cli/
    orientation/
    integration-tests/
    frontend-vue/
```

### What this document changes

At the runtime/product behavior level: the system prompt will correctly enumerate the agent's 9 active tools, fire the `grep`/`find`/`ls`-preference guideline, inline all skills as structured XML so the model can route without an extra tool call, load a user-global `~/.slo/AGENTS.md` before project-local files, and include a self-documentation block routing queries about Slo itself to the right docs paths.

At the file level: `agent.py`, `graph.py` (or both), `project_context.py`, `prompts/__init__.py`, and `prompts/system_prompt.py` each change. One new file, `skills_loader.py`, will be introduced to own skill frontmatter discovery and XML formatting.

At the component level: `SloAgent._resolve_system_prompt` will receive a resolved tool list, `ProjectContextDiscovery.invoke` will grow a user-global tier, `SystemPromptBuilder._build_skills_block` will delegate to a new `SkillsLoader`, and a new `SystemPromptBuilder._build_docs_block` method will be introduced.

---

## 2. Why

The two bugs (B1, B2) mean the model operates with an inaccurate self-description. The tools block says `(none)` even though the model has access to 9 tools; the guidelines block emits only the two ALWAYS_GUIDELINES and never fires the `Prefer grep/find/ls tools over bash for file exploration` line even when bash, grep, find, and ls are all active. This is a correctness failure — the model's stated capability and its actual capability diverge every single session.

The three structural gaps reduce the agent's effectiveness:

- **D1 (skills are pointer-based):** The current skills block tells the model to read `INDEX.md` with the `read` tool at the start of every non-trivial task. In practice, the model frequently skips this extra tool call, especially in shorter tasks, making the entire skill system invisible. Pi inlines every skill's name, description, and path as structured XML so the model sees the full catalogue at zero cost.
- **D4 (no user-global context tier):** Pi loads `~/.pi/AGENTS.md` before any project-level files, giving users a place to store cross-project conventions and personal preferences. Slo stops at the `.git` boundary with no equivalent.
- **D6 (no self-documentation block):** When users ask about Slo's own features — skills, TUI, configuration, extensions — the model has no prompt-level routing hint and must guess file locations. Pi's documentation block solves this by listing exact paths to README, docs/, and examples/ with per-topic routing rules.

---

## 3. Current State

### Prompt assembly (today)

`SystemPromptBuilder.invoke()` at `slo/src/agents/slo_agent/prompts/__init__.py` receives `tools=None` on every normal session and short-circuits the tool and guidelines logic:

```python
# slo/src/agents/slo_agent/prompts/__init__.py  (current — BEFORE)

resolved_tools: Sequence[BaseTool] = tools or ()   # → () when tools=None

# …
sections: list[str] = [
    cls._build_role_line(),
    cls._build_tools_block(tools=resolved_tools),       # → "Available tools:\n(none)"
    cls._build_custom_tools_note(),
    cls._build_guidelines_block(tools=resolved_tools),  # → only 2 ALWAYS_GUIDELINES
    cls._build_skills_block(),                           # → pointer to INDEX.md
    cls._build_knowledge_base_block(),
    cls._build_append_block(append_system_prompt=append_system_prompt),
    cls._build_project_context_block(project_context_files=resolved_project_context_files),
    cls._build_date_line(),
    cls._build_cwd_line(cwd=resolved_cwd),
]
```

The root cause is in `SloAgent.__init__` at `slo/src/agents/slo_agent/agent.py`:

```python
# slo/src/agents/slo_agent/agent.py  (current — BEFORE, lines 146-162)

self._graph: CompiledStateGraph = build_slo_agent(
    model_name=model_name,
    tools=tools,              # tools=None in every normal session
    llm=llm,
    reasoning_level=reasoning_level,
    session_id=session_id,
)
# …
self._system_prompt: str = self._resolve_system_prompt(
    system_prompt=system_prompt,
    tools=tools,              # ← still None; build_slo_agent resolved it internally
    cwd=self._cwd,
    append_system_prompt=append_system_prompt,
    custom_prompt=custom_prompt,
    project_context_files=self._project_context_files,
)
```

`build_slo_agent` at `slo/src/agents/slo_agent/graph.py` silently resolves:

```python
# slo/src/agents/slo_agent/graph.py  (current — BEFORE, lines 293-294)

def build_slo_agent(
    model_name: Optional[str] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    llm: Optional[LLM] = None,
    temperature: Optional[float] = None,
    streaming: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
    reasoning_level: ReasoningLevel = "off",
    session_id: Optional[str] = None,
    tool_execution_mode: ToolExecutionMode = ToolExecutionMode.CONCURRENT_READS,
) -> CompiledStateGraph:
    if tools is None:
        tools = create_extended_tools()   # 9 tools — but this never escapes back to __init__
    # ...
    return graph.compile()
```

### Skills block (today)

`_build_skills_block()` formats `SKILLS_BLOCK_TEMPLATE` with the path to `INDEX.md` and returns a prose paragraph instructing the model to read that file. It does not parse any `SKILL.md` frontmatter and does not produce XML:

```python
# slo/src/agents/slo_agent/prompts/__init__.py  (current — BEFORE)

@classmethod
def _build_skills_block(cls) -> str:
    skills_index_path: str = os.path.join(SKILLS_DIR, "INDEX.md")
    return SKILLS_BLOCK_TEMPLATE.format(
        skills_index_path=skills_index_path,
    ).strip()
```

### Context discovery (today)

`ProjectContextDiscovery.invoke()` at `slo/src/agents/slo_agent/project_context.py` stops the upward walk at the first `.git` ancestor and has no user-global tier:

```python
# slo/src/agents/slo_agent/project_context.py  (current — BEFORE, lines 28-60)

@classmethod
def invoke(cls, *, cwd: str) -> list[tuple[str, str]]:
    cwd_path = Path(cwd).resolve()
    seen_names: set[str] = set()
    results: list[tuple[str, str]] = []

    for directory in cls._walk_up(start=cwd_path):
        for name in cls._PROJECT_FILENAMES:
            candidate = directory / name
            if name in seen_names or not candidate.is_file():
                continue
            seen_names.add(name)
            try:
                content = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            results.append((str(candidate), content))
        if (directory / ".git").exists():
            break                # stops at git root; no ~/.slo/ check

    return results
```

### Current prompt section order and characteristics

| # | Section | Builder method | Stable across turns? |
|---|---------|----------------|----------------------|
| 1 | Role | `_build_role_line` | Yes — constant string |
| 2 | Available tools | `_build_tools_block` | Yes — stable after fix (tool set fixed at construction) |
| 3 | Custom tools note | `_build_custom_tools_note` | Yes — constant string |
| 4 | Guidelines | `_build_guidelines_block` | Yes — stable after fix |
| 5 | Skills block | `_build_skills_block` | Yes — path is fixed |
| 6 | Knowledge base | `_build_knowledge_base_block` | Yes — constant string |
| 7 | Append | `_build_append_block` | Yes — fixed per session |
| 8 | Project context | `_build_project_context_block` | Yes — fixed per session |
| 9 | Date | `_build_date_line` | **No — changes at midnight** |
| 10 | CWD | `_build_cwd_line` | Yes — fixed per session |

---

## 4. Proposed Approach

Fix B1 first (sub-spec 19.a.1) because it unblocks B2 and the guidelines test at zero additional cost: capture the resolved tool list from `build_slo_agent` and forward it to `_resolve_system_prompt`. Once the tool list flows correctly, replace the prose skills block with a structured XML builder (sub-spec 19.a.2). Then extend context discovery with a user-global tier (sub-spec 19.a.3). Author and wire the self-documentation block (sub-spec 19.a.4). Close with an end-to-end verification pass (sub-spec 19.a.5).

### Target interface for the primary seams (AFTER all sub-specs land)

The following shows the key signatures and call sites in their post-change form. Each sub-spec implements one or more of these changes in detail — this overview establishes the contract so sub-spec authors do not diverge.

#### `graph.py` — `build_slo_agent` returns a tuple

```python
# slo/src/agents/slo_agent/graph.py  (AFTER — 19.a.1)

def build_slo_agent(
    model_name: Optional[str] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    llm: Optional[LLM] = None,
    temperature: Optional[float] = None,
    streaming: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
    reasoning_level: ReasoningLevel = "off",
    session_id: Optional[str] = None,
    tool_execution_mode: ToolExecutionMode = ToolExecutionMode.CONCURRENT_READS,
) -> tuple[CompiledStateGraph, Sequence[BaseTool]]:
    """Build a compiled Slo one-shot-turn graph and surface the resolved tool list.

    Returns the compiled graph paired with the tools that were actually bound to
    the LLM. When ``tools=None`` is supplied the extended bundle is resolved
    internally; the caller receives both the graph and the concrete tool list so
    it can forward the list to ``SystemPromptBuilder`` without re-resolving.

    Args:
        model_name (Optional[str]): Model identifier passed to ``LLMFactory.create``.
        tools (Optional[Sequence[BaseTool]]): Tools the agent may call.
            Defaults to ``create_extended_tools()`` (9-tool extended bundle).
        llm (Optional[LLM]): Pre-built chat model for tests.
        temperature (Optional[float]): Forwarded to ``LLMFactory.create``.
        streaming (Optional[bool]): Forwarded to ``LLMFactory.create``.
        max_tokens (Optional[int]): Forwarded to ``LLMFactory.create``.
        max_retries (int): Forwarded to ``LLMFactory.create``. Defaults to 3.
        reasoning_level (ReasoningLevel): Forwarded to ``LLMFactory.create``.
        session_id (Optional[str]): Session identifier for cache attribution.
        tool_execution_mode (ToolExecutionMode): Batch execution policy.

    Returns:
        tuple[CompiledStateGraph, Sequence[BaseTool]]: The compiled graph and
            the resolved tool list that was bound to the LLM.
    """
    if tools is None:
        tools = create_extended_tools()
    # ... build graph as before ...
    return graph.compile(), tools   # ← tools surfaces back to caller
```

#### `agent.py` — `SloAgent.__init__` captures the resolved tool list

```python
# slo/src/agents/slo_agent/agent.py  (AFTER — 19.a.1, lines ~146-170)

self._graph: CompiledStateGraph
resolved_tools: Sequence[BaseTool]
self._graph, resolved_tools = build_slo_agent(
    model_name=model_name,
    tools=tools,
    llm=llm,
    reasoning_level=reasoning_level,
    session_id=session_id,
)
self._cwd: str = cwd if cwd is not None else os.getcwd()
self._project_context_files: list[tuple[str, str]] = ProjectContextDiscovery.invoke(cwd=self._cwd)
self._system_prompt: str = self._resolve_system_prompt(
    system_prompt=system_prompt,
    tools=resolved_tools,         # ← resolved, not the original None
    cwd=self._cwd,
    append_system_prompt=append_system_prompt,
    custom_prompt=custom_prompt,
    project_context_files=self._project_context_files,
)
```

#### `agent.py` — `_resolve_system_prompt` signature tightened

```python
# slo/src/agents/slo_agent/agent.py  (AFTER — 19.a.1)

def _resolve_system_prompt(
    self,
    *,
    system_prompt: Optional[str],
    tools: Sequence[BaseTool],          # was Optional[Sequence[BaseTool]]
    cwd: str,
    append_system_prompt: Optional[str],
    custom_prompt: Optional[str],
    project_context_files: list[tuple[str, str]],
) -> str:
    """Choose between caller override and runtime prompt assembly.

    Called once during agent construction after ``build_slo_agent`` has resolved
    the tool list. When ``system_prompt`` is supplied it is returned unchanged.
    Otherwise delegates to ``SystemPromptBuilder.invoke`` with the concrete
    tool list, which ensures the tools block and guidelines block are accurate.

    Args:
        system_prompt (Optional[str]): Caller-supplied final prompt. Highest-
            precedence override; bypasses all runtime assembly when set.
        tools (Sequence[BaseTool]): Resolved tools already bound to the LLM.
            Never ``None`` — the caller is responsible for resolving before call.
        cwd (str): Working directory for this run.
        append_system_prompt (Optional[str]): Optional text appended after the
            default or custom prompt body.
        custom_prompt (Optional[str]): Optional full body override.
        project_context_files (list[tuple[str, str]]): Discovered project
            guidance files as ``(path, content)`` pairs.

    Returns:
        str: The fully assembled system prompt string.
    """
    if system_prompt is not None:
        return system_prompt
    return SystemPromptBuilder.invoke(
        tools=tools,
        cwd=cwd,
        append_system_prompt=append_system_prompt,
        custom_prompt=custom_prompt,
        project_context_files=project_context_files,
    )
```

#### `project_context.py` — user-global tier prepended (AFTER — 19.a.3)

```python
# slo/src/agents/slo_agent/project_context.py  (AFTER)

_USER_GLOBAL_DIR: Path = Path.home() / ".slo"
_USER_GLOBAL_FILENAMES: ClassVar[tuple[str, ...]] = ("AGENTS.md", "SLO.md", "CLAUDE.md")

@classmethod
def invoke(cls, *, cwd: str) -> list[tuple[str, str]]:
    """Return ``(path, content)`` pairs for instruction files, user-global first.

    Prepends any matching file found under ``~/.slo/`` before walking the
    project tree from ``cwd`` up to the nearest ``.git`` ancestor. User-global
    files are always listed first so project-local files can override them.

    Args:
        cwd (str): Starting directory for the project-local walk.

    Returns:
        list[tuple[str, str]]: ``(absolute_path, content)`` pairs, user-global
            entries first, then deepest-first project-local entries.
    """
    results: list[tuple[str, str]] = cls._load_user_global_files()
    results.extend(cls._load_project_files(cwd=cwd))
    return results
```

#### `prompts/__init__.py` — assembly order after all sub-specs (AFTER)

```python
# slo/src/agents/slo_agent/prompts/__init__.py  (AFTER — 19.a.1 through 19.a.4)

sections: list[str] = [
    cls._build_role_line(),
    cls._build_tools_block(tools=resolved_tools),          # 9 lines — B1 fix
    cls._build_custom_tools_note(),
    cls._build_guidelines_block(tools=resolved_tools),     # fires PREFER_NATIVE — B2 fix
    cls._build_docs_block(),                                # new — D6 fix
    cls._build_skills_block(),                              # XML via SkillsLoader — D1 fix
    cls._build_knowledge_base_block(),
    cls._build_append_block(append_system_prompt=append_system_prompt),
    cls._build_project_context_block(
        project_context_files=resolved_project_context_files,  # includes ~/.slo/ first — D4 fix
    ),
    cls._build_date_line(),
    cls._build_cwd_line(cwd=resolved_cwd),
]
```

---

## 5. Domain Introductions

**Extended tool bundle** — The 9-tool set returned by `create_extended_tools()`: `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`, `read_pdf`, `now`. This is Slo's default tool set, resolved inside `build_slo_agent` when the caller passes `tools=None`.

**SkillsLoader** — A new class (sub-spec 19.a.2) that walks `SKILLS_DIR` at prompt assembly time, parses `SKILL.md` frontmatter (YAML header: `name`, `description`, optional `disable-model-invocation`), and returns a list of `SkillEntryDAO` objects. `SystemPromptBuilder` calls it and feeds the result into a new XML formatter.

Signature contract for `SkillsLoader`:

```python
# slo/src/agents/slo_agent/skills_loader.py  (new file — 19.a.2)

class SkillsLoader:
    """Walk the skills directory and parse per-skill frontmatter into DAOs.

    Called once per session by ``SystemPromptBuilder._build_skills_block``
    at prompt assembly time. The loader reads every ``SKILL.md`` found under
    ``SKILLS_DIR``, extracts the YAML frontmatter fields ``name``,
    ``description``, and the optional ``disable-model-invocation`` flag, and
    returns one ``SkillEntryDAO`` per skill. Skills whose frontmatter cannot
    be parsed are skipped with a warning log.
    """

    @classmethod
    def load(cls, *, skills_dir: str) -> list[SkillEntryDAO]:
        """Discover and parse every skill under ``skills_dir``.

        Args:
            skills_dir (str): Absolute path to the root skills directory.

        Returns:
            list[SkillEntryDAO]: One entry per successfully parsed skill,
                sorted by ``file_path`` for deterministic ordering.
        """
        ...
```

**SkillEntryDAO** — A plain Pydantic model holding `name: str`, `description: str`, `file_path: str`, and `disable_model_invocation: bool` for a single skill entry. Used by `SkillsLoader` and by the XML formatter inside `_build_skills_block`.

```python
# slo/src/agents/slo_agent/skills_loader.py  (new file — 19.a.2)

class SkillEntryDAO(BaseModel):
    """Parsed frontmatter for a single slo skill.

    Populated by ``SkillsLoader.load`` from the YAML header of each
    ``SKILL.md`` file. Used by ``SystemPromptBuilder._build_skills_block``
    to emit the ``<available_skills>`` XML block without an extra tool call.

    Attributes:
        name: Human-readable skill name from the ``name:`` frontmatter key.
        description: One-sentence summary from the ``description:`` key.
        file_path: Absolute path to the ``SKILL.md`` file on disk.
        disable_model_invocation: When ``True`` the skill should not be
            auto-invoked by the model; it requires explicit user opt-in.
            Sourced from the optional ``disable-model-invocation:`` key.
    """

    name: str
    description: str
    file_path: str
    disable_model_invocation: bool = False
```

**User-global context tier** — The `~/.slo/` directory. If `AGENTS.md` (or `SLO.md`, or `CLAUDE.md`) exists there, it is prepended to the context file list before any project-local files. This mirrors Pi's `~/.pi/AGENTS.md` global tier.

**Self-documentation block** — A new prompt section (sub-spec 19.a.4) that lists Slo's own README, docs/ directory, and examples/ with per-topic routing rules. It is rendered only when the slo harness root is discoverable at prompt assembly time.

---

## 6. End-to-End Flow

The prompt assembly flow after all five sub-specs land:

```
SloAgent.__init__(tools=None, ...)
  │
  ├─ build_slo_agent(tools=None)
  │    └─ resolves tools=None → create_extended_tools() [9 tools]
  │    └─ returns (graph, resolved_tools)          ← NEW: tools surface back
  │
  ├─ ProjectContextDiscovery.invoke(cwd=…)
  │    ├─ check ~/.slo/AGENTS.md (user-global tier) ← NEW: D4 fix
  │    └─ walk cwd→.git: collect SLO.md/AGENTS.md/CLAUDE.md
  │
  └─ _resolve_system_prompt(tools=resolved_tools, …)   ← B1 fix
       └─ SystemPromptBuilder.invoke(tools=resolved_tools, …)
            ├─ _build_role_line()
            ├─ _build_tools_block(tools=resolved_tools)
            │    └─ "read: …\nwrite: …\nbash: …\n…"   ← 9 lines, not "(none)"
            ├─ _build_custom_tools_note()
            ├─ _build_guidelines_block(tools=resolved_tools)
            │    └─ "Prefer grep/find/ls tools over bash…" fires ← B2 fix
            ├─ _build_docs_block()                     ← NEW: D6 fix
            ├─ _build_skills_block()
            │    └─ SkillsLoader.load() → [SkillEntryDAO, …]
            │    └─ _format_skills_xml([…])            ← NEW: D1 fix
            ├─ _build_knowledge_base_block()
            ├─ _build_append_block(…)
            ├─ _build_project_context_block(…)
            │    └─ includes ~/.slo/AGENTS.md first   ← D4 fix
            ├─ _build_date_line()
            └─ _build_cwd_line(…)
```

`_build_initial_messages` at `slo/src/agents/slo_agent/agent.py` then prepends the assembled string as a `SystemMessage` on every turn. The system prompt is computed once at construction, so all turns in a session share the same cache-stable prefix.

---

## 7. Sub-Spec Map

| Filename | Title | Priority | Depends on | What it changes |
|----------|-------|----------|-----------|-----------------|
| `19.a.1-tool-list-wiring.md` | Tool List Wiring (B1 + B2) | P0 | — | `agent.py`, `graph.py`: capture resolved tools from `build_slo_agent` and pass them to `_resolve_system_prompt`; unblocks correct tools block and guidelines block |
| `19.a.2-skills-xml-inlining.md` | Skills XML Inlining (D1) | P1 | 19.a.1 | New `skills_loader.py` (`SkillsLoader`, `SkillEntryDAO`); replace `_build_skills_block` prose pointer with Pi-compatible XML; add `disable-model-invocation` support |
| `19.a.3-user-global-context-tier.md` | User-Global Context Tier (D4) | P1 | 19.a.1 | `project_context.py`: prepend `~/.slo/AGENTS.md` (and `SLO.md`, `CLAUDE.md`) before project-local walk; no walk-to-root change (stop at `.git` kept) |
| `19.a.4-self-documentation-block.md` | Self-Documentation Block (D6) | P2 | 19.a.1 | `prompts/system_prompt.py`: author `SLO_DOCS_BLOCK_TEMPLATE`; `prompts/__init__.py`: wire new `_build_docs_block()` into assembly order |
| `19.a.5-verification-and-closeout.md` | Verification and Closeout | P2 | 19.a.1–4 | End-to-end smoke guide, regression test checklist, acceptance gate |

---

## 8. Current vs. Target System Prompt Structure

### Current (broken) prompt structure

| # | Section | Content in a default session |
|---|---------|------------------------------|
| 1 | Role | "You are an expert coding assistant operating inside slo…" |
| 2 | Available tools | `Available tools:`  `(none)` — **bug B1** |
| 3 | Custom tools note | Static text about project-specific tools |
| 4 | Guidelines | `Guidelines:` + 2 always-guidelines only — **bug B2** (bash/grep preference line absent) |
| 5 | Skills | Prose paragraph pointing to `INDEX.md` — **gap D1** |
| 6 | Knowledge base | `## Knowledge Base` with `SLO_KB_DIR` guidance |
| 7 | Append | *(empty — only fires when `append_system_prompt` is set)* |
| 8 | Project context | `<project_context>` XML with `SLO.md` / `AGENTS.md` / `CLAUDE.md` found up to `.git` — **no `~/.slo/` tier (gap D4)** |
| 9 | Date | `Current date: 2026-06-13` |
| 10 | CWD | `Current working directory: /path` |

No self-documentation block — **gap D6**.

### Target (after all sub-specs) prompt structure

| # | Section | Content in a default session |
|---|---------|------------------------------|
| 1 | Role | "You are an expert coding assistant operating inside slo…" |
| 2 | Available tools | `Available tools:` + 9 bullet lines (read, write, edit, bash, grep, find, ls, read_pdf, now) |
| 3 | Custom tools note | Same static text |
| 4 | Guidelines | `Guidelines:` + `Prefer grep/find/ls tools over bash…` + 2 always-guidelines |
| 5 | Self-documentation | `Slo documentation (read only when…):` block with README path, docs/ paths, per-topic routing |
| 6 | Skills | Pi-compatible XML: `<available_skills>` with one `<skill>` element per discovered skill (name + description + absolute path) |
| 7 | Knowledge base | Same `## Knowledge Base` block |
| 8 | Append | *(empty unless set)* |
| 9 | Project context | `<project_context>` XML — `~/.slo/AGENTS.md` first (if present), then project-local files up to `.git` |
| 10 | Date | `Current date: 2026-06-13` |
| 11 | CWD | `Current working directory: /path` |

---

## 9. Prompt Caching Economics

### Why inlining skills is net cheaper

Anthropic charges **1.25× the input token price to write a cache entry** and **0.1× (10%) the input token price to read a hit**. A typical Slo session with AGENTS.md, CLAUDE.md, and a few dozen skills inlined produces a system prompt of approximately 6,000–8,000 tokens.

Break-even on the cache-write premium occurs well before turn 3:

```
write cost      = 1.25 × base_input_price × 7000 tokens
per-turn saving = (1.0 - 0.1) × base_input_price × 7000 tokens
                = 0.9 × base × 7000

turns to break even = write_premium / per_turn_saving
                    = (0.25 × base × 7000) / (0.9 × base × 7000)
                    = 0.25 / 0.9
                    ≈ 0.28 turns — i.e., from turn 2 onward the session is ahead
```

In practice the Anthropic SDK's automatic cache-control header means the prefix is cached on the first turn and every subsequent turn costs 10% of the base input price for the prompt portion. A 20-turn coding session on a 7,000-token prompt costs roughly the same in total prompt tokens as a session with a 1,000-token prompt on turn 3 onward.

The alternative — keeping skills as a pointer and letting the model call `read` for `INDEX.md` — costs more. Each `INDEX.md` read is a tool-call round-trip (one extra turn at full output-token price) that also extends the context window with the index content for the remainder of the session. Inlining the XML at construction time eliminates this tax entirely and guarantees the skill catalogue is visible.

### OpenAI

OpenAI applies automatic prompt caching on GPT-4o and o-series models (Responses API). The harness does not need to do anything special: stable prefixes are cached automatically by the platform. Inlining skills still benefits from this — the XML block is stable per session, so it lands in the cached prefix on every session after the first.

### Section order and cache stability

The `_build_date_line()` section is the only section that can change mid-session (at midnight). All other sections are stable for the lifetime of a session instance because they are computed once in `SloAgent.__init__`. Placing `_build_date_line()` and `_build_cwd_line()` last maximizes the stable prefix length — everything before them is cache-eligible from the very first turn.

The self-documentation block (D6 fix) and the skills XML block (D1 fix) are placed before the project context block and the date/cwd footer. This means they are part of the stable, cacheable middle of the prompt while the project-context block (which varies per project) comes later.

---

## 10. Priority Order

```
P0  19.a.1 — Tool list wiring (B1 + B2)
        no prerequisite changes needed
        unblocks: 19.a.2, 19.a.3, 19.a.4, 19.a.5

P1  19.a.2 — Skills XML inlining (D1)
        depends on: 19.a.1
        can run in parallel with: 19.a.3

P1  19.a.3 — User-global context tier (D4)
        depends on: 19.a.1
        can run in parallel with: 19.a.2

P2  19.a.4 — Self-documentation block (D6)
        depends on: 19.a.1
        standalone; does not interact with 19.a.2 or 19.a.3

P2  19.a.5 — Verification and closeout
        depends on: 19.a.1, 19.a.2, 19.a.3, 19.a.4
        gate: all four P0/P1/P2 changes must land first
```

Dependency diagram:

```
19.a.1 (B1+B2: tool list wiring)  — P0
    ├──→ 19.a.2 (D1: skills XML)         — P1
    ├──→ 19.a.3 (D4: user-global tier)   — P1
    └──→ 19.a.4 (D6: self-docs block)    — P2
              └──(all four)──→ 19.a.5 (verification) — P2
```

---

## 11. Dependencies

**What blocks this feature:** None. The current codebase is the starting point; no other in-flight feature modifies the prompt assembly path.

**What this feature blocks downstream:** Any feature that assumes the prompt correctly describes the agent's tool set (e.g. a future `/tools` command that reads the prompt's tools block to display active tools) should land after 19.a.1. The skills XML format (19.a.2) is a prerequisite for any future skill-routing analytics or `/skills` TUI commands.

---

## 12. Test Coverage Requirements

Each sub-spec must cover the decision points it introduces. This section enumerates the minimum required test cases that the suite must contain once all sub-specs land. Sub-spec authors must not move to a next sub-spec until all tests for the current one are green.

### 19.a.1 — Tool list wiring

| Decision point | Required test |
|----------------|---------------|
| `build_slo_agent(tools=None)` resolves to extended bundle | Assert return tuple contains 9 tools matching `create_extended_tools()` |
| `build_slo_agent(tools=<explicit_list>)` passes list through unchanged | Assert return tuple second element is the same list object |
| `SloAgent.__init__(tools=None)` produces tools block with 9 entries | Inspect `_system_prompt`; assert `"(none)"` is not present |
| `_resolve_system_prompt(system_prompt=<override>)` returns override unchanged | Assert result equals the override string without calling builder |
| `_resolve_system_prompt(system_prompt=None)` calls `SystemPromptBuilder.invoke` | Mock builder; assert called once with `tools=resolved_tools` (non-empty) |
| Guidelines block fires `GUIDELINE_PREFER_NATIVE_EXPLORERS` when bash+grep+find+ls all present | Assert rendered guidelines contains the preference line |
| Guidelines block fires `GUIDELINE_BASH_ONLY` when only bash present | Assert rendered guidelines contains bash-only line |
| Guidelines block emits only `ALWAYS_GUIDELINES` when no bash present | Assert neither bash guideline line appears |

### 19.a.2 — Skills XML inlining

| Decision point | Required test |
|----------------|---------------|
| `SkillsLoader.load` with a directory containing valid `SKILL.md` files | Assert one `SkillEntryDAO` per file with correct `name`, `description`, `file_path` |
| `SkillsLoader.load` with a `SKILL.md` missing required frontmatter key | Assert that file is skipped; other files still returned |
| `SkillsLoader.load` with `disable-model-invocation: true` in frontmatter | Assert `SkillEntryDAO.disable_model_invocation` is `True` |
| `SkillsLoader.load` with empty skills directory | Assert returns empty list |
| `_build_skills_block` with a non-empty `SkillsLoader` result | Assert output starts with `<available_skills>` and contains one `<skill>` per entry |
| `_build_skills_block` with an empty `SkillsLoader` result | Assert output is an empty string or a defined fallback, not a prose pointer |

### 19.a.3 — User-global context tier

| Decision point | Required test |
|----------------|---------------|
| `ProjectContextDiscovery.invoke` when `~/.slo/AGENTS.md` exists | Assert that entry appears first in returned list |
| `ProjectContextDiscovery.invoke` when `~/.slo/` does not exist | Assert no error; project-local files returned normally |
| `ProjectContextDiscovery.invoke` when `~/.slo/AGENTS.md` exists and project also has `AGENTS.md` | Assert both entries present; `~/.slo/` entry is first |
| `_load_user_global_files` when none of the three filenames exist under `~/.slo/` | Assert returns empty list |

### 19.a.4 — Self-documentation block

| Decision point | Required test |
|----------------|---------------|
| `_build_docs_block` when slo harness root is discoverable | Assert output is non-empty and contains expected README path |
| `_build_docs_block` when slo harness root cannot be determined | Assert returns empty string (no KeyError, no exception) |

---

## 13. Acceptance Criteria

All criteria must be verifiable by a reviewer running the harness locally with the default `SloAgent()` constructor and no arguments.

1. **B1 — Tools block no longer reads `(none)`:** Constructing `SloAgent()` with no arguments and inspecting `agent._system_prompt` must show a line beginning `Available tools:` followed by exactly 9 `- <tool_name>: …` lines matching the names in `create_extended_tools()`. The string `(none)` must not appear in the tools section.

2. **B2 — Grep/find/ls guideline fires in every default session:** `agent._system_prompt` must contain the string `Prefer grep/find/ls tools over bash for file exploration` when the default 9-tool bundle is active.

3. **D1 — Skills block is Pi-compatible XML:** `agent._system_prompt` must contain `<available_skills>` with at least one `<skill>` child element whose attributes include `name`, `description`, and `path`. The prose paragraph pointing to `INDEX.md` must not appear in the skills section.

4. **D4 — User-global context tier is loaded when present:** Creating `~/.slo/AGENTS.md` with arbitrary content and constructing `SloAgent()` must result in a `_system_prompt` that includes that file's content inside the `<project_context>` block, appearing before any project-local instruction file content.

5. **D6 — Self-documentation block is present:** `agent._system_prompt` must contain a recognizable self-documentation header (e.g., `Slo documentation`) followed by at least one absolute path reference to a Slo harness file.

6. **No regressions on existing tests:** Running `pytest slo/tests/` against the post-feature codebase must produce zero failures in any test that was previously passing.

7. **`build_slo_agent` return type is a tuple:** Calling `build_slo_agent()` must return a 2-tuple `(CompiledStateGraph, Sequence[BaseTool])`. Any existing code that assigned the return value to a single variable must be updated to unpack the tuple.

8. **`SkillsLoader.load` is deterministic:** Calling `SkillsLoader.load(skills_dir=SKILLS_DIR)` twice in the same process must return lists with the same entries in the same order.

----

# Sub Step Sample

> **Path**
> <feature-specifications-root>/20-system-prompt-analysis-and-pi-parity/01-fix-tools-passthrough.md


---
Status: READY
Owner: ragequilt
Last updated: 2026-06-13
Parent spec: specifications/18-system-prompt-analysis-and-pi-parity.md
Branch: feature-fix_system_prompt_tool_wiring
Repo: <repository-root>
Approx. size: XS — 2 files changed, ~15 lines net diff, 4 new tests
---

# Step 18 — Fix B1/B2: Wire Resolved Tool List from `build_slo_agent` Back to System Prompt Builder

## 1. Context

### Description

`build_slo_agent` resolves a concrete tool list (defaulting to `create_extended_tools()` when the caller passes `None`), but this resolved list is discarded before it reaches `SloAgent.__init__`. The graph is compiled with all nine tools bound. The system prompt, however, is built from the *original* `tools` parameter — which is still `None` when no override was supplied. `SystemPromptBuilder.invoke(tools=None)` then resolves `tools or ()` to an empty tuple, emitting "Available tools:\n(none)" and suppressing every tool-specific guideline in the prompt. The LLM silently loses its instruction surface while retaining full tool capability.

This sub-spec fixes Bugs B1 and B2 by changing `build_slo_agent` to return both the compiled graph **and** the resolved tool list via a new `SloAgentBuildResult` named-tuple, and updating `SloAgent.__init__` to thread `result.tools` into `_resolve_system_prompt`.

### Big Picture

This is a wiring-only fix at a single architectural seam: the handoff between `graph.py` (graph factory) and `agent.py` (stateful wrapper). No graph topology changes, no new nodes, no new LangChain constructs. The fix is the minimal change that makes the agent's system prompt consistent with its bound tool set in the default case, and it is a prerequisite for the full pi-parity prompt work described in spec 18. No downstream code outside these two files is touched.

### Existing structure we are extending

```
slo/src/agents/slo_agent/
├── graph.py                     # build_slo_agent() — graph factory
├── agent.py                     # SloAgent — stateful wrapper; consumes build_slo_agent()
├── prompts/
│   ├── __init__.py              # SystemPromptBuilder.invoke()
│   └── system_prompt.py        # prompt wording constants
└── ...

slo/src/agents/tools/
└── bundles.py                   # create_extended_tools() and sibling factories

slo/tests/agents/slo_agent/
├── test_agent.py                # SloAgent public-surface tests
├── test_graph.py                # build_slo_agent / graph topology tests
└── test_prompts.py              # SystemPromptBuilder tests
```

### What this document changes

**Runtime / product behavior:** When `SloAgent` is constructed without an explicit `tools` override, the system prompt now lists all nine extended tools and includes the `GUIDELINE_PREFER_NATIVE_EXPLORERS` bullet (`"Prefer grep/find/ls tools over bash for file exploration (faster, respects .gitignore)"`). Previously the prompt said `"Available tools:\n(none)"` and the guidelines block contained only the always-on bullets.

**File-level changes:**
- `slo/src/agents/slo_agent/graph.py` — `build_slo_agent` return type changes from `CompiledStateGraph` to `SloAgentBuildResult`; the function gains a `SloAgentBuildResult` NamedTuple definition and returns `SloAgentBuildResult(graph=graph.compile(), tools=tools)`.
- `slo/src/agents/slo_agent/agent.py` — `SloAgent.__init__` unpacks `result = build_slo_agent(...)` and passes `result.tools` instead of `tools` to `_resolve_system_prompt`.

**Component-level changes:**
- `build_slo_agent` return type: `CompiledStateGraph` → `SloAgentBuildResult`.
- `SloAgent.__init__` body: `self._graph = build_slo_agent(...)` → `_result = build_slo_agent(...)` + `self._graph = _result.graph`.
- `_resolve_system_prompt` call site: `tools=tools` → `tools=_result.tools`.

---

## 2. Why

The agent's graph and system prompt must agree on the active tool set. When they diverge the model operates under false constraints: it will call tools correctly (because the graph's `llm.bind_tools(...)` is correct) but the prompt gives it no instructions about what those tools do, when to prefer native explorers, or how to apply tool-specific guidelines. The result is a degraded agent that happens to work mechanically but lacks the operational context that the prompt was designed to supply.

The root cause is a local-variable scoping mistake: `build_slo_agent` resolves `tools` in its own frame and never surfaces that resolved value to the caller. Fixing it by introducing a thin result container (`SloAgentBuildResult`) is the minimal, zero-regression change: existing callers that only care about the graph can access `result.graph`; the agent can now also access `result.tools`.

---

## 3. Current State

### Bug B1 — Root cause: resolved `tools` is local to `build_slo_agent`

In `slo/src/agents/slo_agent/graph.py` at lines 250–261, `build_slo_agent` is declared to return `CompiledStateGraph`:

```python
# slo/src/agents/slo_agent/graph.py  lines 250-261
def build_slo_agent(
    model_name: Optional[str] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    llm: Optional[LLM] = None,
    temperature: Optional[float] = None,
    streaming: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
    reasoning_level: ReasoningLevel = "off",
    session_id: Optional[str] = None,
    tool_execution_mode: ToolExecutionMode = ToolExecutionMode.CONCURRENT_READS,
) -> CompiledStateGraph:
```

At lines 293–294, the function resolves `tools` to the default bundle when the caller passed `None`:

```python
# slo/src/agents/slo_agent/graph.py  lines 293-294
    if tools is None:
        tools = create_extended_tools()
```

The local variable `tools` is now the full nine-tool list. The graph is built with all tools bound (line 308):

```python
# slo/src/agents/slo_agent/graph.py  line 308
    llm_with_tools: BaseChatModel = llm.bind_tools(tools=list(tools)) if tools else llm
```

At line 329 the function returns only the compiled graph, discarding the resolved tool list entirely:

```python
# slo/src/agents/slo_agent/graph.py  line 329
    return graph.compile()
```

### Bug B2 — Propagation: `SloAgent.__init__` passes the un-resolved `tools=None` to `_resolve_system_prompt`

In `slo/src/agents/slo_agent/agent.py` at lines 146–162, `SloAgent.__init__` calls `build_slo_agent` and then immediately calls `_resolve_system_prompt` with the same `tools` argument it received — which is still `None` when the caller did not supply an override:

```python
# slo/src/agents/slo_agent/agent.py  lines 146-162  (BEFORE)
        self._graph: CompiledStateGraph = build_slo_agent(
            model_name=model_name,
            tools=tools,        # None when caller used default
            llm=llm,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )
        self._cwd: str = cwd if cwd is not None else os.getcwd()
        self._project_context_files: list[tuple[str, str]] = ProjectContextDiscovery.invoke(cwd=self._cwd)
        self._system_prompt: str = self._resolve_system_prompt(
            system_prompt=system_prompt,
            tools=tools,        # still None — the resolved list was never returned
            cwd=self._cwd,
            append_system_prompt=append_system_prompt,
            custom_prompt=custom_prompt,
            project_context_files=self._project_context_files,
        )
```

`_resolve_system_prompt` (lines 174–217) delegates to `SystemPromptBuilder.invoke` with `tools=None`:

```python
# slo/src/agents/slo_agent/agent.py  lines 208-217
        return SystemPromptBuilder.invoke(
            tools=tools,        # None
            cwd=cwd,
            custom_prompt=custom_prompt,
            append_system_prompt=append_system_prompt,
            project_context_files=project_context_files,
        )
```

`SystemPromptBuilder.invoke` (line 75 of `slo/src/agents/slo_agent/prompts/__init__.py`) resolves `None` to an empty tuple:

```python
# slo/src/agents/slo_agent/prompts/__init__.py  line 75
        resolved_tools: Sequence[BaseTool] = tools or ()
```

With an empty `resolved_tools`:

- `_build_tools_block(tools=())` → `"Available tools:\n(none)"` (lines 145–171 of `prompts/__init__.py`).
- `_build_guidelines_block(tools=())` → `tool_names` is the empty set, so the `"bash" in tool_names` branch never fires and `GUIDELINE_PREFER_NATIVE_EXPLORERS` is never added.

### Complete broken call chain summary

```
SloAgent.__init__(tools=None)
  │
  ├─ build_slo_agent(tools=None)
  │     └─ if tools is None: tools = create_extended_tools()   # resolved locally
  │     └─ llm.bind_tools(tools=list(tools))                   # graph has all 9 tools ✓
  │     └─ return graph.compile()                              # resolved list discarded ✗
  │
  └─ _resolve_system_prompt(tools=tools)                       # tools still None
        └─ SystemPromptBuilder.invoke(tools=None)
              └─ resolved_tools = tools or () = ()
              └─ _build_tools_block(tools=())  → "Available tools:\n(none)"  ✗
              └─ _build_guidelines_block(tools=())  → no tool-specific guidelines ✗
```

---

## 4. Proposed Approach

Introduce a `SloAgentBuildResult` NamedTuple that carries both the compiled graph and the resolved tool list. `build_slo_agent` returns this instead of the bare `CompiledStateGraph`. `SloAgent.__init__` unpacks the result, stores the graph, and passes the resolved tool list to `_resolve_system_prompt`.

This approach was preferred over alternatives for the following reasons:

- **No interface breakage on `SystemPromptBuilder`.** The builder already accepts `Sequence[BaseTool]`; we only need to supply it with non-`None` input.
- **No new mutable state.** The resolved tool list is captured once at construction time and used once for prompt assembly; it does not need to be stored on the agent instance unless a later spec requires it.
- **Minimal blast radius.** Only two files change. Tests that call `build_slo_agent` directly and then use the result as a graph (e.g. `test_graph.py` lines 65, 86) will need to be updated to access `result.graph` — but they need to change in any case now that the return type changes.
- **Unambiguous semantics.** A NamedTuple is immutable and self-documenting at the return site. The field names `graph` and `tools` match the canonical vocabulary used throughout the codebase.

---

## 5. Domain Introductions

### `SloAgentBuildResult`

A lightweight container that pairs a compiled LangGraph `CompiledStateGraph` with the `Sequence[BaseTool]` that was actually bound to the LLM inside that graph. It exists because `build_slo_agent` needs to surface two values to its caller without changing the public API surface of `SloAgent` and without requiring callers to call a separate resolver. The resolved tool list is the same object that was passed to `llm.bind_tools`, so the graph and the system prompt are guaranteed to describe the same capabilities.

---

## 6. End-to-End Flow

After the fix, the runtime slice for a default `SloAgent()` construction looks like this:

```
SloAgent.__init__(tools=None)
  │
  ├─ _result = build_slo_agent(tools=None)
  │     └─ if tools is None: tools = create_extended_tools()
  │           → [read, write, edit, bash, grep, find, ls, read_pdf, now]  (9 tools)
  │     └─ llm.bind_tools(tools=list(tools))   # graph binds all 9 ✓
  │     └─ return SloAgentBuildResult(
  │                  graph=graph.compile(),
  │                  tools=tools             # now surfaced to caller ✓
  │              )
  │
  ├─ self._graph = _result.graph
  │
  └─ _resolve_system_prompt(tools=_result.tools)
        │   tools is now [read, write, edit, bash, grep, find, ls, read_pdf, now]
        └─ SystemPromptBuilder.invoke(tools=<9 tools>)
              └─ resolved_tools = tools or () = <9 tools>
              └─ _build_tools_block(tools=<9 tools>)
              │     → "Available tools:\n- read: ...\n- write: ...\n..."  ✓
              └─ _build_guidelines_block(tools=<9 tools>)
                    tool_names = {"read","write","edit","bash","grep","find","ls","read_pdf","now"}
                    "bash" in tool_names → True
                    {"grep","find","ls"} & tool_names → {"grep","find","ls"} (non-empty)
                    → GUIDELINE_PREFER_NATIVE_EXPLORERS fires  ✓
```

When the caller supplies an explicit tool list (e.g. `SloAgent(tools=[stub_now])`) the flow is unchanged: `build_slo_agent` sees a non-`None` `tools` argument, skips the `if tools is None` branch, and `SloAgentBuildResult.tools` equals the caller-supplied list.

When the caller supplies a `system_prompt` override, `_resolve_system_prompt` returns early on line 208 (`if system_prompt is not None: return system_prompt`), so the corrected tool propagation path is simply bypassed. No behavior change for that case.

---

## 7. Implementation Details

### 7.1 Implementation order

1. Edit `slo/src/agents/slo_agent/graph.py` — add `SloAgentBuildResult` NamedTuple and update `build_slo_agent`.
2. Edit `slo/src/agents/slo_agent/agent.py` — update `SloAgent.__init__` to unpack `SloAgentBuildResult`.
3. Update the existing call sites in `test_graph.py` that call `build_slo_agent` and use the result directly as a graph (`.ainvoke`, `graph =` etc.).
4. Add new tests to `test_agent.py`.

### 7.2 Change 1 — `graph.py`: introduce `SloAgentBuildResult` and update return

The `SloAgentBuildResult` NamedTuple is defined at module scope, near the other public symbols, before `build_slo_agent`. The `__all__` list, the return type annotation, and the final `return` statement all change.

**BEFORE** (complete function — lines 250–329):

```python
# slo/src/agents/slo_agent/graph.py  lines 250-329  (BEFORE)
def build_slo_agent(
    model_name: Optional[str] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    llm: Optional[LLM] = None,
    temperature: Optional[float] = None,
    streaming: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
    reasoning_level: ReasoningLevel = "off",
    session_id: Optional[str] = None,
    tool_execution_mode: ToolExecutionMode = ToolExecutionMode.CONCURRENT_READS,
) -> CompiledStateGraph:
    """Build a compiled Slo one-shot-turn graph.

    The returned graph performs **one assistant turn + one tool batch**
    per invocation. The multi-turn ReAct loop is driven by
    ``SloAgent.react_streaming``.

    Args:
        model_name (Optional[str]): Model identifier passed to
            ``LLMFactory.create``. Falls back to ``cfg("DEFAULT_MODEL_NAME")``.
            Ignored when ``llm`` is supplied directly.
        tools (Optional[Sequence[BaseTool]]): Tools the agent may call.
            Defaults to ``create_extended_tools()`` (the full pi-parity
            bundle plus ``read_pdf`` and ``now``). This deliberately
            departs from pi's narrower ``createCodingTools`` default —
            slo ships document- and timestamp-aware capabilities
            out of the box.
        llm (Optional[LLM]): Pre-built chat model — use this to inject a
            ``FauxChatModel`` for tests. When provided,
            ``model_name``/``temperature``/``streaming``/``max_tokens``
            are ignored.
        temperature, streaming, max_tokens, max_retries: Forwarded to
            ``LLMFactory.create`` when ``llm`` is not supplied.
        reasoning_level (ReasoningLevel): Canonical active reasoning
            level forwarded into ``LLMFactory.create``.
        tool_execution_mode (ToolExecutionMode): Batch execution policy
            for the custom Slo tool node.

    Returns:
        CompiledStateGraph: A compiled ``StateGraph`` ready for
            ``.astream()`` / ``.ainvoke()``.
    """
    if tools is None:
        tools = create_extended_tools()

    if llm is None:
        resolved_model: str = model_name or (cfg(key="DEFAULT_MODEL_NAME") or "gpt-5.4")
        llm = LLMFactory.create(
            model_name=resolved_model,
            temperature=temperature,
            streaming=streaming,
            max_retries=max_retries,
            max_tokens=max_tokens,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )

    llm_with_tools: BaseChatModel = llm.bind_tools(tools=list(tools)) if tools else llm

    agent_node: NodeFn = _make_agent_node(llm_with_tools=llm_with_tools)
    tool_node: NodeFn = _make_tool_node(
        tools=tools,
        execution_mode=tool_execution_mode,
    )

    # Linear, one-shot turn:
    #
    #   START ──► agent ──► tools ──► END
    #
    # No conditional edges, no routing function. Looping is the caller's
    # responsibility — see ``SloAgent.react_streaming``.
    graph: StateGraph = StateGraph(SloAgentStateDAO)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", "tools")
    graph.add_edge("tools", END)

    return graph.compile()
```

**AFTER** — add `SloAgentBuildResult` before the function (after the `__all__` block), update `__all__`, change return type annotation, update docstring Returns section, and change the final return statement:

```python
# slo/src/agents/slo_agent/graph.py  (AFTER — insert SloAgentBuildResult before build_slo_agent;
#                                      also add "SloAgentBuildResult" to __all__)

from typing import NamedTuple  # add NamedTuple to existing typing import

class SloAgentBuildResult(NamedTuple):
    """Pair the compiled graph with the tool list actually bound to the LLM.

    ``build_slo_agent`` may resolve a default tool list internally when the
    caller passes ``tools=None``. This container surfaces that resolved list
    alongside the compiled graph so that callers (specifically
    ``SloAgent.__init__``) can pass the same tool list to downstream
    components such as ``SystemPromptBuilder``.

    Attributes:
        graph (CompiledStateGraph): The compiled LangGraph ready for
            ``.astream()`` / ``.ainvoke()``.
        tools (Sequence[BaseTool]): The tool list that was bound to the LLM
            via ``llm.bind_tools(tools=...)``. Never ``None``; defaults to
            the result of ``create_extended_tools()`` when the caller did not
            supply an override.
    """

    graph: CompiledStateGraph
    tools: Sequence[BaseTool]
```

```python
# slo/src/agents/slo_agent/graph.py  (AFTER — complete updated function)
def build_slo_agent(
    model_name: Optional[str] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    llm: Optional[LLM] = None,
    temperature: Optional[float] = None,
    streaming: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
    reasoning_level: ReasoningLevel = "off",
    session_id: Optional[str] = None,
    tool_execution_mode: ToolExecutionMode = ToolExecutionMode.CONCURRENT_READS,
) -> SloAgentBuildResult:
    """Build a compiled Slo one-shot-turn graph.

    The returned ``SloAgentBuildResult`` carries both the compiled graph and
    the resolved tool list. When ``tools`` is ``None`` the function resolves
    the default bundle (``create_extended_tools()``) before building; the
    resolved list is returned alongside the graph so that callers can pass it
    to ``SystemPromptBuilder`` without re-resolving it independently.

    Args:
        model_name (Optional[str]): Model identifier passed to
            ``LLMFactory.create``. Falls back to ``cfg("DEFAULT_MODEL_NAME")``.
            Ignored when ``llm`` is supplied directly.
        tools (Optional[Sequence[BaseTool]]): Tools the agent may call.
            Defaults to ``create_extended_tools()`` when ``None``.
        llm (Optional[LLM]): Pre-built chat model — use this to inject a
            ``FauxChatModel`` for tests. When provided,
            ``model_name``/``temperature``/``streaming``/``max_tokens``
            are ignored.
        temperature, streaming, max_tokens, max_retries: Forwarded to
            ``LLMFactory.create`` when ``llm`` is not supplied.
        reasoning_level (ReasoningLevel): Canonical active reasoning level
            forwarded into ``LLMFactory.create``.
        tool_execution_mode (ToolExecutionMode): Batch execution policy for
            the custom Slo tool node.

    Returns:
        SloAgentBuildResult: Named tuple of ``(graph, tools)`` where
            ``graph`` is the compiled ``StateGraph`` and ``tools`` is the
            resolved, non-``None`` tool list that was bound to the LLM.
    """
    if tools is None:
        tools = create_extended_tools()

    if llm is None:
        resolved_model: str = model_name or (cfg(key="DEFAULT_MODEL_NAME") or "gpt-5.4")
        llm = LLMFactory.create(
            model_name=resolved_model,
            temperature=temperature,
            streaming=streaming,
            max_retries=max_retries,
            max_tokens=max_tokens,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )

    llm_with_tools: BaseChatModel = llm.bind_tools(tools=list(tools)) if tools else llm

    agent_node: NodeFn = _make_agent_node(llm_with_tools=llm_with_tools)
    tool_node: NodeFn = _make_tool_node(
        tools=tools,
        execution_mode=tool_execution_mode,
    )

    # Linear, one-shot turn:
    #
    #   START ──► agent ──► tools ──► END
    #
    # No conditional edges, no routing function. Looping is the caller's
    # responsibility — see ``SloAgent.react_streaming``.
    graph: StateGraph = StateGraph(SloAgentStateDAO)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", "tools")
    graph.add_edge("tools", END)

    return SloAgentBuildResult(graph=graph.compile(), tools=tools)
```

### 7.3 Change 2 — `agent.py`: unpack `SloAgentBuildResult` in `__init__`

`SloAgent.__init__` stores the graph and passes the resolved tool list to `_resolve_system_prompt`. The name `_result` is used as the local variable to avoid shadowing the `tools` parameter name (which callers may still supply explicitly).

**BEFORE** (lines 146–162):

```python
# slo/src/agents/slo_agent/agent.py  lines 146-162  (BEFORE)
        self._graph: CompiledStateGraph = build_slo_agent(
            model_name=model_name,
            tools=tools,
            llm=llm,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )
        self._cwd: str = cwd if cwd is not None else os.getcwd()
        self._project_context_files: list[tuple[str, str]] = ProjectContextDiscovery.invoke(cwd=self._cwd)
        self._system_prompt: str = self._resolve_system_prompt(
            system_prompt=system_prompt,
            tools=tools,
            cwd=self._cwd,
            append_system_prompt=append_system_prompt,
            custom_prompt=custom_prompt,
            project_context_files=self._project_context_files,
        )
```

**AFTER** — unpack `_result`; pass `_result.tools` to `_resolve_system_prompt`:

```python
# slo/src/agents/slo_agent/agent.py  lines 146-162  (AFTER)
        _result: SloAgentBuildResult = build_slo_agent(
            model_name=model_name,
            tools=tools,
            llm=llm,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )
        self._graph: CompiledStateGraph = _result.graph
        self._cwd: str = cwd if cwd is not None else os.getcwd()
        self._project_context_files: list[tuple[str, str]] = ProjectContextDiscovery.invoke(cwd=self._cwd)
        self._system_prompt: str = self._resolve_system_prompt(
            system_prompt=system_prompt,
            tools=_result.tools,
            cwd=self._cwd,
            append_system_prompt=append_system_prompt,
            custom_prompt=custom_prompt,
            project_context_files=self._project_context_files,
        )
```

The `from src.agents.slo_agent.graph import SloAgentStateDAO, build_slo_agent` import line (agent.py line 45) must be extended to import `SloAgentBuildResult`:

```python
# slo/src/agents/slo_agent/agent.py  line 45  (AFTER)
from src.agents.slo_agent.graph import SloAgentBuildResult, SloAgentStateDAO, build_slo_agent
```

### 7.4 Update existing `test_graph.py` call sites

The two tests in `test_graph.py` that currently assign the return of `build_slo_agent` directly to a `graph` variable (lines 65 and 86) must be updated to access `.graph`:

**BEFORE** (line 65):
```python
    graph = build_slo_agent(llm=faux, tools=[stub_echo])
```

**AFTER**:
```python
    graph = build_slo_agent(llm=faux, tools=[stub_echo]).graph
```

Similarly for line 86 and any other direct call sites in that file. The `test_build_slo_agent_threads_reasoning_level_into_llm_factory` test on line 36 does not capture the return value, so it needs no change beyond verifying the mock call.

### 7.5 Verification commands

```bash
# From the repo root, with the project virtualenv active:
cd "$SLO_ROOT_DIR"

# Run only the directly affected tests first:
python -m pytest -sv slo/tests/agents/slo_agent/test_graph.py
python -m pytest -sv slo/tests/agents/slo_agent/test_agent.py
python -m pytest -sv slo/tests/agents/slo_agent/test_prompts.py

# Full suite to confirm no regressions:
python -m pytest -sv slo/tests/
```

### 7.6 Manual smoke check

Start `SloAgent()` with no arguments and inspect `_system_prompt`:

```python
from src.agents.slo_agent.agent import SloAgent
from src.agents.providers import FauxChatModel

agent = SloAgent(llm=FauxChatModel(responses=[]))
print(agent._system_prompt)
# Expect: "Available tools:" followed by read, write, edit, bash, grep, find, ls, read_pdf, now entries
# Expect: "Prefer grep/find/ls tools over bash for file exploration" in Guidelines section
# Must NOT contain: "Available tools:\n(none)"
```

---

## 8. Tests

All new tests belong in `slo/tests/agents/slo_agent/test_agent.py`. They use `FauxChatModel` and do not touch the network.

### Test 1 — `SystemPromptBuilder` receives the full default tool list

This test verifies that the `SystemPromptBuilder` is called with 9 tools when no `tools` override is supplied. It patches `SystemPromptBuilder.invoke` to intercept the call and inspects the `tools` keyword argument.

```python
# slo/tests/agents/slo_agent/test_agent.py
from unittest.mock import patch, MagicMock

def test_system_prompt_builder_receives_nine_tools_when_no_tools_override() -> None:
    """SystemPromptBuilder.invoke receives 9 tools when SloAgent is built with default tools.

    Regression test for Bug B2: before the fix, SloAgent passed ``tools=None``
    to SystemPromptBuilder because the resolved tool list was local to
    ``build_slo_agent`` and never returned to the caller.
    """
    captured_tools: list = []

    original_invoke = __import__(
        "src.agents.slo_agent.prompts",
        fromlist=["SystemPromptBuilder"],
    ).SystemPromptBuilder.invoke

    def _capturing_invoke(**kwargs):
        captured_tools.extend(kwargs.get("tools") or [])
        return original_invoke(**kwargs)

    with patch(
        "src.agents.slo_agent.agent.SystemPromptBuilder.invoke",
        side_effect=_capturing_invoke,
    ):
        SloAgent(llm=FauxChatModel(responses=[]))

    assert len(captured_tools) == 9, (
        f"Expected 9 tools forwarded to SystemPromptBuilder, got {len(captured_tools)}: "
        f"{[t.name for t in captured_tools]}"
    )
```

### Test 2 — Default system prompt does not contain "(none)"

This test verifies the symptom directly: the assembled system prompt must list tools, not the fallback `"(none)"` sentinel.

```python
# slo/tests/agents/slo_agent/test_agent.py
def test_default_system_prompt_lists_tools_not_none() -> None:
    """The default system prompt must not contain the '(none)' fallback string.

    Regression test for Bug B1: before the fix, ``_build_tools_block`` received
    an empty tool sequence and emitted ``'Available tools:\\n(none)'``.
    """
    agent = SloAgent(llm=FauxChatModel(responses=[]))
    assert "Available tools:\n(none)" not in agent._system_prompt, (
        "System prompt still contains '(none)' — resolved tool list was not "
        "propagated from build_slo_agent to SystemPromptBuilder"
    )
    assert "Available tools:" in agent._system_prompt
```

### Test 3 — `GUIDELINE_PREFER_NATIVE_EXPLORERS` fires in the default prompt

This test verifies that the guideline branch dependent on the presence of both `bash` and native explorer tools (`grep`, `find`, `ls`) fires correctly once the prompt builder receives the real tool list.

```python
# slo/tests/agents/slo_agent/test_agent.py
def test_default_system_prompt_includes_prefer_native_explorers_guideline() -> None:
    """The default prompt must include the 'Prefer grep/find/ls' guideline.

    The guideline fires only when the tool set contains 'bash' AND at least one
    of {grep, find, ls}. Before the B1/B2 fix the tool set was always empty,
    so neither the bash-only nor the native-explorers branch ever fired.
    """
    agent = SloAgent(llm=FauxChatModel(responses=[]))
    assert "Prefer grep/find/ls tools over bash" in agent._system_prompt, (
        "GUIDELINE_PREFER_NATIVE_EXPLORERS not found in system prompt — "
        "tool list was empty when SystemPromptBuilder ran"
    )
```

### Test 4 — Explicit tool override is still respected (non-regression)

This test guards against accidental regression where passing an explicit tool list might be overridden by the default.

```python
# slo/tests/agents/slo_agent/test_agent.py
def test_explicit_tool_override_is_preserved_in_system_prompt() -> None:
    """An explicit tools list passed to SloAgent is forwarded to SystemPromptBuilder unchanged.

    Verifies that the B1/B2 fix does not accidentally replace an explicit tool
    override with the default extended bundle.
    """
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def bash(cmd: str) -> str:
        """Run a shell command."""
        return ""

    agent = SloAgent(
        llm=FauxChatModel(responses=[]),
        tools=[bash],
    )
    # With a one-tool list containing only bash (no grep/find/ls),
    # the bash-only guideline fires, not the prefer-native-explorers one.
    assert "Use bash for file operations" in agent._system_prompt
    assert "Prefer grep/find/ls tools over bash" not in agent._system_prompt
```

### Test 5 — `build_slo_agent` result carries 9 tools when called with `tools=None`

This test directly validates the `SloAgentBuildResult` contract: calling `build_slo_agent` without a tool override must return a result whose `.tools` field has exactly 9 entries (the `create_extended_tools()` default bundle). This is the direct unit test for the return-type change.

```python
# slo/tests/agents/slo_agent/test_graph.py
def test_build_slo_agent_result_carries_nine_tools_when_tools_is_none() -> None:
    """SloAgentBuildResult.tools has 9 entries when build_slo_agent is called without a tool override.

    Directly tests the B1 fix: before the fix, the resolved list was never
    surfaced in the return value. After the fix, result.tools equals
    create_extended_tools() and has length 9.
    """
    faux = FauxChatModel(responses=[])
    result = build_slo_agent(llm=faux)
    assert len(result.tools) == 9, (
        f"Expected 9 tools in SloAgentBuildResult.tools, got {len(result.tools)}: "
        f"{[t.name for t in result.tools]}"
    )
```

---

## 9. Acceptance Criteria

- [ ] `build_slo_agent` return type annotation is `SloAgentBuildResult`, not `CompiledStateGraph`. Verified by inspection and by `mypy --strict` on `graph.py` passing cleanly.
- [ ] `SloAgentBuildResult` is a `NamedTuple` with exactly two fields: `graph: CompiledStateGraph` and `tools: Sequence[BaseTool]`.
- [ ] `SloAgentBuildResult.tools` is never `None`. When the caller passes `tools=None` the field equals `create_extended_tools()` (9 tools). Verified directly by `test_build_slo_agent_result_carries_nine_tools_when_tools_is_none` in `test_graph.py` asserting `len(result.tools) == 9`.
- [ ] `SloAgent(llm=FauxChatModel(...))._system_prompt` does not contain the string `"Available tools:\n(none)"`. Verified by `test_default_system_prompt_lists_tools_not_none`.
- [ ] `SloAgent(llm=FauxChatModel(...))._system_prompt` contains `"Prefer grep/find/ls tools over bash"`. Verified by `test_default_system_prompt_includes_prefer_native_explorers_guideline`.
- [ ] `SystemPromptBuilder.invoke` receives `len(tools) == 9` when `SloAgent` is constructed without a tool override. Verified by `test_system_prompt_builder_receives_nine_tools_when_no_tools_override`.
- [ ] When `SloAgent(tools=[bash])` is constructed with a single-tool explicit override, `SystemPromptBuilder` receives exactly that one tool, not 9. Verified by `test_explicit_tool_override_is_preserved_in_system_prompt`.
- [ ] All existing tests in `test_graph.py`, `test_agent.py`, and `test_prompts.py` pass without modification beyond the `build_slo_agent().graph` call-site updates in `test_graph.py`.
- [ ] `python -m pytest -sv slo/tests/` exits 0.

---

## 10. Dependencies

**Blocks this slice:** None. This is a self-contained wiring fix that depends only on existing code.

**Blocked by this slice:**
- The full pi-parity prompt analysis work in `specifications/18-system-prompt-analysis-and-pi-parity.md` assumes the tool list is correctly forwarded to `SystemPromptBuilder`. That work should not begin until this fix is merged and green.
- Any future spec that stores `self._tools` on `SloAgent` for runtime introspection or dynamic prompt updates should source the list from `_result.tools` (or the stored attribute derived from it), not from re-resolving `create_extended_tools()` independently.

---

# Second Sub-Step Sample

> **Path**
>
> <feature-specifications-root>/20-system-prompt-analysis-and-pi-parity/02-skills-xml-inline.md

---
Status: Draft
Owner: ragequilt
Last updated: 2026-06-13
Parent spec: specifications/18-system-prompt-analysis-and-pi-parity.md
Branch: feature-skills_xml_inline_injection
Repo: <repository-root>
Approx. size: ~350 LOC (new: ~200, modified: ~150)
---

# Step 19 — Skills XML Inline Injection (Pi-Parity)

## 1. Context

### Changes

Replace the prose `SKILLS_BLOCK_TEMPLATE` (which directs the model to read `skills/INDEX.md` via the `read` tool) with Pi's structured `<available_skills>` XML block, injected directly into the system prompt at agent construction time by scanning all `SKILL.md` frontmatter at startup.

### Big Picture

This slice sits at the intersection of three concerns: agent reliability, prompt-cache stability, and Pi-format parity. The skills system today is invisible to the model whenever it skips the `read INDEX.md` step — an increasingly common failure mode for tasks the model considers "obvious". Pi solved this by front-loading skill metadata at session startup: scan, parse, inject once. The injected XML is static for the lifetime of a session, making it an excellent prompt-cache target.

This is a contained, single-boundary change: the scanner (`SkillsLoader`) is new, `SystemPromptBuilder` gains one new helper and a changed signature for `_build_skills_block`, and `SloAgent.__init__` acquires one new call before delegating to the builder. Nothing downstream of the system prompt string changes.

### Existing structure we are extending

```
slo/
  config/
    cfg.py                           # SKILLS_DIR constant, _resolve_skills_dir()
  skills/
    INDEX.md                         # Currently the only entry point the model sees
    design-and-analysis/
      feature-specifications/
        SKILL.md                     # YAML frontmatter: name, description, when_to_use, group, kind
      specification-development/
        SKILL.md
      ...
    git-ops/
      commit-and-push/
        SKILL.md
      ...
    coding/
      build-routers/
        SKILL.md
      ...
  src/
    agents/
      slo_agent/
        agent.py                     # SloAgent.__init__, _resolve_system_prompt
        project_context.py           # ProjectContextDiscovery (reference pattern)
        prompts/
          __init__.py                # SystemPromptBuilder, SYSTEM_PROMPT
          system_prompt.py           # SKILLS_BLOCK_TEMPLATE, all prompt constants
  tests/
    agents/
      slo_agent/
        test_project_context.py      # Pattern to follow for filesystem-scanning tests
        test_prompts.py              # Existing SystemPromptBuilder tests (must stay green)
```

Current `SKILLS_BLOCK_TEMPLATE` in `slo/src/agents/slo_agent/prompts/system_prompt.py` (lines 56–80):

```python
SKILLS_BLOCK_TEMPLATE: str = """\
## Skills

Slo ships a curated set of skills under `skills/`. They cover several kinds of work:
...
The full list of available skills lives at `{skills_index_path}`. At the start of any
non-trivial task, read `{skills_index_path}` with the `read` tool to see what conventions
or workflows apply. ...
"""
```

Current `SystemPromptBuilder._build_skills_block` in `slo/src/agents/slo_agent/prompts/__init__.py` (lines 211–221):

```python
@classmethod
def _build_skills_block(cls) -> str:
    skills_index_path: str = os.path.join(SKILLS_DIR, "INDEX.md")
    return SKILLS_BLOCK_TEMPLATE.format(
        skills_index_path=skills_index_path,
    ).strip()
```

### What this document changes

**Runtime/product behavior:** The agent no longer needs to read `INDEX.md` to discover available skills. Every session starts with skills metadata directly visible in the system prompt as structured XML. The agent can route to the correct `SKILL.md` by reading the `<location>` tag rather than first reading the index.

**File-level changes:**

| File | Change |
|---|---|
| `slo/src/agents/slo_agent/skills_loader.py` | **New.** `SkillEntryDAO` Pydantic model + `SkillsLoader` classmethod interface |
| `slo/src/agents/slo_agent/prompts/system_prompt.py` | Remove `SKILLS_BLOCK_TEMPLATE`. Add `SKILLS_XML_PREAMBLE` constant and `SKILLS_FALLBACK_BLOCK`. Update `__all__`. |
| `slo/src/agents/slo_agent/prompts/__init__.py` | Update `_build_skills_block` signature and body; add `_format_skills_as_xml` and `_escape_xml`; update `invoke()` to accept `skills` kwarg |
| `slo/src/agents/slo_agent/agent.py` | Call `SkillsLoader.load()` in `__init__`, thread `skills` into `_resolve_system_prompt` and down to `SystemPromptBuilder.invoke()` |
| `slo/tests/agents/slo_agent/test_skills_loader.py` | **New.** Eight tests for the loader |
| `slo/tests/agents/slo_agent/test_prompts.py` | Update three existing tests that assert on `SKILLS_BLOCK_TEMPLATE` wording; add three new tests |

**Component-level changes:** `SloAgent._resolve_system_prompt` gains a `skills` parameter. `SystemPromptBuilder.invoke()` gains a `skills: Optional[list[SkillEntryDAO]]` keyword. `_build_skills_block` becomes `_build_skills_block(skills: list[SkillEntryDAO])`.

---

## 2. Why

**The INDEX.md pointer is a latent skip hazard.** When the agent judges a task "obvious" it skips the `read INDEX.md` step entirely, making the skill system invisible for that session. For short or common tasks this happens routinely. Pi identified and closed the same gap by front-loading skill metadata at startup rather than gating discovery on a read call.

**XML is a machine-readable format at a stable cost.** The injected block contains only frontmatter metadata (name, description, file path), not the full `SKILL.md` body. At ~60 skills × ~3 lines each, the injection adds roughly 180 lines to the system prompt — well within Anthropic's 32K cache granule threshold — and because the content is purely static within a session, it is an ideal cache anchor.

**It closes a Pi-parity gap.** `specifications/18-system-prompt-analysis-and-pi-parity.md` enumerates gaps between Slo's current prompt and Pi's output. The skills block is the most impactful remaining gap: Pi's `formatSkillsForPrompt()` in `pi/packages/coding-agent/src/core/skills.ts` produces the XML block shown in this spec's Context section, and the format is already validated in Pi's production sessions.

---

## 3. Current State

**`SKILLS_BLOCK_TEMPLATE`** (the thing being replaced) lives at `slo/src/agents/slo_agent/prompts/system_prompt.py:56–80`. It is a prose string with one `{skills_index_path}` placeholder that the builder interpolates from `config.cfg.SKILLS_DIR`. The template tells the model where the index lives and instructs it to read it. It does not surface any skill names or descriptions.

**`SystemPromptBuilder._build_skills_block()`** (the method being changed) at `slo/src/agents/slo_agent/prompts/__init__.py:211–221` calls `os.path.join(SKILLS_DIR, "INDEX.md")` and formats the template. It takes no arguments.

**`SloAgent._resolve_system_prompt()`** at `slo/src/agents/slo_agent/agent.py:174–217` delegates to `SystemPromptBuilder.invoke()` with `tools`, `cwd`, `custom_prompt`, `append_system_prompt`, and `project_context_files`. It does not currently carry a `skills` argument.

**The SKILL.md frontmatter schema** as seen in the existing tree:

```yaml
---
name: feature-specifications           # required; must be unique
description: Style guide for writing technical feature specifications.
when_to_use: 'Use when authoring a spec...'
group: design-and-analysis
kind: workflow
source_prompt: analyze/feature-specifications.md
---
```

The `disable-model-invocation` key is not yet used in any existing `SKILL.md` but is defined in Pi's TypeScript interface and must be respected when present so that internal/meta skills can be excluded from the XML.

**Active constraints:**

- `SYSTEM_PROMPT: str = SystemPromptBuilder.invoke()` at module import time (line 372 of `prompts/__init__.py`) — the module-level constant must still compile. After this change it will reflect the XML-injected prompt (using a live scan of `SKILLS_DIR`).
- Existing test `test_invoke_points_at_skills_index` in `test_prompts.py` asserts `"skills/INDEX.md" in prompt`. This test must be updated — the new prompt no longer contains the INDEX.md path reference (it contains individual `<location>` paths instead).
- The test `test_invoke_advertises_both_coding_and_analysis_skills` asserts `"Coding-convention skills" in prompt`. This text lives in `SKILLS_BLOCK_TEMPLATE` which is being removed; the test must be updated to assert on the XML preamble or on actual skill descriptions from the tree.

---

## 4. Proposed Approach

The implementation follows Pi's approach precisely:

1. **Scan once at session startup.** `SkillsLoader.load()` walks `SKILLS_DIR` recursively, collects every `SKILL.md`, parses the YAML frontmatter with PyYAML (already present via LangChain), and returns a `list[SkillEntryDAO]`. Skills with malformed frontmatter are logged and skipped. Skills with `disable-model-invocation: true` are filtered out. The scan is synchronous (filesystem reads on startup are acceptable; `SKILLS_DIR` contains ~60 files).

2. **Build the XML block at prompt assembly time.** `SystemPromptBuilder._build_skills_block(skills)` delegates to `_format_skills_as_xml(skills)` which renders the exact Pi XML format. When `skills` is empty (e.g. `SKILLS_DIR` is missing), the method falls back to a short static preamble directing the model to read `INDEX.md` — exactly the existing `SKILLS_BLOCK_TEMPLATE` behavior.

3. **Thread `skills` through the call chain.** `SloAgent.__init__` calls `SkillsLoader.load()` after `ProjectContextDiscovery.invoke()` and before `_resolve_system_prompt()`. `_resolve_system_prompt` gains a `skills` parameter, `SystemPromptBuilder.invoke()` gains a `skills` keyword, and `_build_skills_block` consumes it.

4. **No XML escaping library required.** The skill names, descriptions, and file paths in the committed tree contain no `&`, `<`, `>`, `"`, or `'` characters. The formatter will still apply XML escaping via a simple five-substitution helper to match Pi's `escapeXml()` behavior and be safe against future skills.

The design intentionally keeps `SkillsLoader` decoupled from `SystemPromptBuilder`: the loader knows about the filesystem; the builder knows about prompt formatting. `SloAgent` is the composition root that wires the two together.

---

## 5. Domain Introductions

**`SkillEntryDAO`** — a Pydantic value object representing a single skill as seen by the system prompt. It carries only the information needed for the XML block: the skill's canonical name, its one-line description, the absolute filesystem path to its `SKILL.md`, and the `disable_model_invocation` flag. It does not carry the skill body, `when_to_use`, `group`, or `kind` — those remain in the `SKILL.md` for the model to read on demand.

**`SkillsLoader`** — a stateless class with one public classmethod, `load()`. It owns the filesystem scan, YAML frontmatter parsing, filtering, and fallback. It parallels `ProjectContextDiscovery` in role: both are startup-time filesystem scanners that feed the prompt builder. Callers never instantiate it; they call `SkillsLoader.load(skills_dir=...)`.

**`_format_skills_as_xml()`** — a private helper on `SystemPromptBuilder` that converts a `list[SkillEntryDAO]` into the Pi-format XML string. It is the single point where the XML shape is defined; all escape logic is local to it.

**`SKILLS_FALLBACK_BLOCK`** — a new string constant in `system_prompt.py` that replaces `SKILLS_BLOCK_TEMPLATE` in the fallback path (empty skills list). It retains the INDEX.md-pointing prose for backward compatibility when `SKILLS_DIR` is missing or empty. Like `SKILLS_BLOCK_TEMPLATE` before it, this constant contains a `{skills_index_path}` placeholder that `_build_skills_block` interpolates at assembly time.

**`SKILLS_XML_PREAMBLE`** — a new string constant that holds the three instructional lines that precede the `<available_skills>` block in Pi's format:

```
The following skills provide specialized instructions for specific tasks.
Use the read tool to load a skill's file when the task matches its description.
When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.
```

---

## 6. End-to-End Flow

The runtime slice for a normal session startup with `skills/` present:

```
SloAgent.__init__(model_name="claude-sonnet-4-6", cwd="<project-root>")
  │
  ├─ build_slo_agent(...)                          # graph compiled, tools wired
  │
  ├─ self._cwd = cwd or os.getcwd()
  │
  ├─ ProjectContextDiscovery.invoke(cwd=self._cwd)
  │    └─ returns [("<project-root>/AGENTS.md", "...content...")]
  │
  ├─ SkillsLoader.load(skills_dir=SKILLS_DIR)      # NEW
  │    ├─ Path(SKILLS_DIR).rglob("SKILL.md")
  │    │    iterates ~103 SKILL.md files
  │    ├─ For each file:
  │    │    ├─ read_text() → raw
  │    │    ├─ parse YAML frontmatter between "---" delimiters
  │    │    ├─ skip if "disable-model-invocation: true"
  │    │    ├─ skip + log_warning if frontmatter missing / malformed / no description
  │    │    └─ append SkillEntryDAO(name=..., description=..., file_path=abs_path)
  │    └─ returns list[SkillEntryDAO] (~100 entries)
  │
  ├─ _resolve_system_prompt(
  │      system_prompt=None, tools=None, cwd=self._cwd,
  │      append_system_prompt=None, custom_prompt=None,
  │      project_context_files=[...],
  │      skills=[SkillEntryDAO(...), ...]            # NEW
  │  )
  │    └─ SystemPromptBuilder.invoke(
  │           tools=None, cwd=self._cwd,
  │           custom_prompt=None, append_system_prompt=None,
  │           project_context_files=[...],
  │           skills=[SkillEntryDAO(...), ...]       # NEW
  │       )
  │         └─ _build_skills_block(skills=[...])
  │               └─ _format_skills_as_xml(skills=[...])
  │                    ├─ builds SKILLS_XML_PREAMBLE
  │                    ├─ for each SkillEntryDAO: renders <skill> element
  │                    └─ returns full XML string
  │
  └─ self._system_prompt = assembled prompt string
       now contains <available_skills> block instead of INDEX.md pointer
```

Fallback path when `SKILLS_DIR` does not exist or is empty:

```
SkillsLoader.load(skills_dir="/nonexistent")
  └─ Path.rglob() finds nothing (or path does not exist → caught, logged)
  └─ returns []

_build_skills_block(skills=[])
  └─ returns SKILLS_FALLBACK_BLOCK (the INDEX.md-pointer prose, unchanged from today)
```

---

## 7. Implementation Details

### Implementation order

1. Add `SkillEntryDAO` and `SkillsLoader` to `slo/src/agents/slo_agent/skills_loader.py` (new file).
2. Replace `SKILLS_BLOCK_TEMPLATE` in `slo/src/agents/slo_agent/prompts/system_prompt.py` with `SKILLS_XML_PREAMBLE` and `SKILLS_FALLBACK_BLOCK`; update `__all__`.
3. Update `slo/src/agents/slo_agent/prompts/__init__.py`: update imports, update `invoke()` signature, add `_format_skills_as_xml()` and `_escape_xml()`, update `_build_skills_block()`.
4. Update `slo/src/agents/slo_agent/agent.py`: import `SkillsLoader` and `SkillEntryDAO`, add the `SkillsLoader.load()` call, thread `skills` through `_resolve_system_prompt`.
5. Write new tests in `slo/tests/agents/slo_agent/test_skills_loader.py`.
6. Update existing tests in `slo/tests/agents/slo_agent/test_prompts.py` (three assertions break; three new ones needed).

### Step 1 — `skills_loader.py` (new file)

`SkillEntryDAO` is a Pydantic BaseModel with `model_config = ConfigDict(frozen=True)`. `SkillsLoader.load()` is the sole public surface. It handles three failure modes silently: directory not found, unreadable file, and malformed/missing frontmatter. In each case it logs at warning level and continues.

```python
# slo/src/agents/slo_agent/skills_loader.py

"""Startup scanner for slo skill metadata.

Walks the SKILLS_DIR tree, extracts YAML frontmatter from every SKILL.md,
and returns a list of SkillEntryDAO values ready for injection into the
system prompt as structured XML (sub-spec 19).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict

from config.logger import log_info, log_warning

__all__ = ["SkillEntryDAO", "SkillsLoader"]


class SkillEntryDAO(BaseModel):
    """Metadata for a single skill, extracted from its SKILL.md frontmatter.

    Only the fields needed for the XML prompt block are retained here. The
    full skill body (when_to_use, group, kind, instructional content) remains
    in the SKILL.md file and is loaded by the agent on demand via the read
    tool.

    Attributes:
        name: Canonical skill identifier, taken from the ``name`` frontmatter
            key, falling back to the parent directory name when absent.
        description: One-line description of what the skill does. Required;
            skills without a description are excluded from the XML block.
        file_path: Absolute path to the SKILL.md file. Used as the
            ``<location>`` value in the XML block so the agent can load the
            skill without needing to know the full tree layout.
        disable_model_invocation: When True the skill is internal / meta and
            must not appear in the model-visible XML block. Defaults to False.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    file_path: str
    disable_model_invocation: bool = False


class SkillsLoader:
    """Scan the SKILL.md tree and return a list of prompt-ready skill entries.

    This class has no instance state. All behavior is in the ``load()``
    classmethod. It is the filesystem-scanning counterpart of
    ``ProjectContextDiscovery``: both are called once during ``SloAgent``
    construction, both feed the ``SystemPromptBuilder``, and both swallow
    transient filesystem errors to avoid crashing agent startup.
    """

    _FRONTMATTER_DELIMITER: str = "---"

    @classmethod
    def load(cls, *, skills_dir: str) -> list[SkillEntryDAO]:
        """Scan ``skills_dir`` recursively and return prompt-ready skill entries.

        Walks the directory tree under ``skills_dir`` looking for files named
        ``SKILL.md``. Each file is parsed for its YAML frontmatter block (the
        section between the first two ``---`` delimiters). Skills that are
        missing a ``description`` key or that carry ``disable-model-invocation:
        true`` are excluded. All other parse failures (missing file, invalid
        YAML, no frontmatter) are logged at WARNING level and skipped.

        Args:
            skills_dir (str): Absolute path to the root of the skills tree
                (typically ``config.cfg.SKILLS_DIR``).

        Returns:
            list[SkillEntryDAO]: Parsed, filtered skill entries in filesystem
                discovery order (depth-first, lexicographic within each
                directory). Returns an empty list when ``skills_dir`` does
                not exist or contains no valid SKILL.md files.
        """
        skills_path: Path = Path(skills_dir)
        if not skills_path.is_dir():
            log_warning(
                msg="SkillsLoader: skills_dir not found; skills XML will not be injected",
                skills_dir=skills_dir,
            )
            return []

        entries: list[SkillEntryDAO] = []
        skill_file: Path
        for skill_file in sorted(skills_path.rglob("SKILL.md")):
            entry: Optional[SkillEntryDAO] = cls._parse_skill_file(
                skill_file=skill_file,
            )
            if entry is None:
                continue
            if entry.disable_model_invocation:
                continue
            entries.append(entry)

        log_info(
            msg="SkillsLoader: loaded skills",
            count=len(entries),
            skills_dir=skills_dir,
        )
        return entries

    @classmethod
    def _parse_skill_file(
        cls,
        *,
        skill_file: Path,
    ) -> Optional[SkillEntryDAO]:
        """Parse a single SKILL.md file and return its SkillEntryDAO.

        ``load()`` calls this once per discovered SKILL.md. The method extracts
        the frontmatter block (the text between the first two ``---`` lines),
        parses it with PyYAML, and assembles a ``SkillEntryDAO``. Returns
        ``None`` and emits a warning instead of raising when any step fails —
        one bad file must not abort the whole scan.

        Args:
            skill_file (Path): Absolute path to the SKILL.md file to parse.

        Returns:
            Optional[SkillEntryDAO]: Parsed entry, or ``None`` when the file
                is unreadable, has no frontmatter block, has invalid YAML, or
                is missing the required ``description`` key.
        """
        try:
            raw: str = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            log_warning(
                msg="SkillsLoader: could not read SKILL.md; skipping",
                path=str(skill_file),
                error=str(exc),
            )
            return None

        frontmatter: Optional[dict[str, Any]] = cls._extract_frontmatter(
            raw=raw,
            path=skill_file,
        )
        if frontmatter is None:
            return None

        description: Optional[str] = frontmatter.get("description")
        if not description:
            log_warning(
                msg="SkillsLoader: SKILL.md has no description; skipping",
                path=str(skill_file),
            )
            return None

        name: str = frontmatter.get("name") or skill_file.parent.name
        disable: bool = bool(frontmatter.get("disable-model-invocation", False))

        return SkillEntryDAO(
            name=name,
            description=str(description).strip(),
            file_path=str(skill_file.resolve()),
            disable_model_invocation=disable,
        )

    @classmethod
    def _extract_frontmatter(
        cls,
        *,
        raw: str,
        path: Path,
    ) -> Optional[dict[str, Any]]:
        """Extract and parse the YAML frontmatter block from raw SKILL.md text.

        ``_parse_skill_file()`` delegates frontmatter extraction here to keep
        error handling centralized. The method looks for the first ``---``
        delimiter, collects lines until the second ``---``, and parses the
        block with PyYAML. Returns ``None`` (with a warning log) when no
        frontmatter block is present, when the YAML is invalid, or when the
        parsed value is not a mapping (dict).

        Args:
            raw (str): Full text content of the SKILL.md file.
            path (Path): File path used only for warning messages.

        Returns:
            Optional[dict[str, Any]]: Parsed frontmatter as a plain dictionary,
                or ``None`` on any parse failure.
        """
        lines: list[str] = raw.splitlines()
        if not lines or lines[0].strip() != cls._FRONTMATTER_DELIMITER:
            log_warning(
                msg="SkillsLoader: SKILL.md has no frontmatter block; skipping",
                path=str(path),
            )
            return None

        end_index: Optional[int] = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == cls._FRONTMATTER_DELIMITER:
                end_index = i
                break

        if end_index is None:
            log_warning(
                msg="SkillsLoader: SKILL.md frontmatter block not closed; skipping",
                path=str(path),
            )
            return None

        frontmatter_text: str = "\n".join(lines[1:end_index])
        try:
            parsed: object = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            log_warning(
                msg="SkillsLoader: malformed YAML in SKILL.md frontmatter; skipping",
                path=str(path),
                error=str(exc),
            )
            return None

        if not isinstance(parsed, dict):
            log_warning(
                msg="SkillsLoader: SKILL.md frontmatter parsed to non-dict; skipping",
                path=str(path),
            )
            return None

        return parsed
```

### Step 2 — `system_prompt.py` changes

Remove `SKILLS_BLOCK_TEMPLATE`. Add two new constants. Update `__all__`. The rest of the file is unchanged.

**Before (lines 19–31 and 56–80):**

```python
# slo/src/agents/slo_agent/prompts/system_prompt.py  [BEFORE]

__all__ = [
    "ROLE_LINE",
    "CUSTOM_TOOLS_NOTE",
    "GUIDELINES_HEADER",
    "ALWAYS_GUIDELINES",
    "GUIDELINE_BASH_ONLY",
    "GUIDELINE_PREFER_NATIVE_EXPLORERS",
    "SKILLS_BLOCK_TEMPLATE",
    "KB_BLOCK",
    "PROJECT_CONTEXT_OPEN",
    "PROJECT_CONTEXT_CLOSE",
    "PROJECT_INSTRUCTIONS_TEMPLATE",
]

# ... (lines 33–55 unchanged) ...

SKILLS_BLOCK_TEMPLATE: str = """\
## Skills

Slo ships a curated set of skills under `skills/`. They cover several kinds of work:

- **Coding-convention skills** — how to build routers, agent tools, services, domain
  features, Vue components, write tests, apply style rules, scaffold a project, etc.
- **Git-ops skills** — how to sync `main`, create task branches, commit safely, push,
  generate PR text, open PRs, load PR context, fix review feedback, and use worktrees.
- **Analysis and workflow skills** — how to break down a feature spec, gather context
  for a spec, write one, verify one, trace how something works in the codebase, debug
  by isolation, run integration tests, generate test plans, and so on.

Each skill is a markdown file with YAML frontmatter (`name`, `description`,
`when_to_use`, `group`, `kind`) and instructional content for one kind of task.
The index is grouped into workflows and individual skills so routing is fast.

The full list of available skills lives at `{skills_index_path}`. At the start of any
non-trivial task, read `{skills_index_path}` with the `read` tool to see what conventions
or workflows apply. When the task description matches a skill's description or
`when_to_use` hint, load that skill's `SKILL.md` (the path is listed in the index) and
follow its instructions precisely before writing code or producing output. Skills are
not optional — when one matches, it is the authoritative source for that kind of work.
Some skills name companion skills to load alongside them (a "pre-hook" or
"post-hook"); honour those."""
```

**After:**

```python
# slo/src/agents/slo_agent/prompts/system_prompt.py  [AFTER]

__all__ = [
    "ROLE_LINE",
    "CUSTOM_TOOLS_NOTE",
    "GUIDELINES_HEADER",
    "ALWAYS_GUIDELINES",
    "GUIDELINE_BASH_ONLY",
    "GUIDELINE_PREFER_NATIVE_EXPLORERS",
    "SKILLS_XML_PREAMBLE",
    "SKILLS_FALLBACK_BLOCK",
    "KB_BLOCK",
    "PROJECT_CONTEXT_OPEN",
    "PROJECT_CONTEXT_CLOSE",
    "PROJECT_INSTRUCTIONS_TEMPLATE",
]

# ... (lines 33–55 unchanged) ...

SKILLS_XML_PREAMBLE: str = (
    "The following skills provide specialized instructions for specific tasks.\n"
    "Use the read tool to load a skill's file when the task matches its description.\n"
    "When a skill file references a relative path, resolve it against the skill directory "
    "(parent of SKILL.md / dirname of the path) and use that absolute path in tool commands."
)

SKILLS_FALLBACK_BLOCK: str = """\
## Skills

Slo ships a curated set of skills under `skills/`. They cover several kinds of work:

- **Coding-convention skills** — how to build routers, agent tools, services, domain
  features, Vue components, write tests, apply style rules, scaffold a project, etc.
- **Git-ops skills** — how to sync `main`, create task branches, commit safely, push,
  generate PR text, open PRs, load PR context, fix review feedback, and use worktrees.
- **Analysis and workflow skills** — how to break down a feature spec, gather context
  for a spec, write one, verify one, trace how something works in the codebase, debug
  by isolation, run integration tests, generate test plans, and so on.

Each skill is a markdown file with YAML frontmatter (`name`, `description`,
`when_to_use`, `group`, `kind`) and instructional content for one kind of task.
The index is grouped into workflows and individual skills so routing is fast.

The full list of available skills lives at `{skills_index_path}`. At the start of any
non-trivial task, read `{skills_index_path}` with the `read` tool to see what conventions
or workflows apply. When the task description matches a skill's description or
`when_to_use` hint, load that skill's `SKILL.md` (the path is listed in the index) and
follow its instructions precisely before writing code or producing output. Skills are
not optional — when one matches, it is the authoritative source for that kind of work.
Some skills name companion skills to load alongside them (a "pre-hook" or
"post-hook"); honour those."""
```

### Step 3 — `prompts/__init__.py` changes

Three changes: updated import, new `_format_skills_as_xml` and `_escape_xml` helpers, updated `_build_skills_block` and `invoke` signatures.

**Updated imports (BEFORE):**

```python
# slo/src/agents/slo_agent/prompts/__init__.py  [BEFORE — import block]

from src.agents.slo_agent.prompts.system_prompt import (
    ALWAYS_GUIDELINES,
    CUSTOM_TOOLS_NOTE,
    GUIDELINE_BASH_ONLY,
    GUIDELINE_PREFER_NATIVE_EXPLORERS,
    GUIDELINES_HEADER,
    KB_BLOCK,
    PROJECT_CONTEXT_CLOSE,
    PROJECT_CONTEXT_OPEN,
    PROJECT_INSTRUCTIONS_TEMPLATE,
    ROLE_LINE,
    SKILLS_BLOCK_TEMPLATE,
)
```

**Updated imports (AFTER):**

```python
# slo/src/agents/slo_agent/prompts/__init__.py  [AFTER — import block]

from src.agents.slo_agent.prompts.system_prompt import (
    ALWAYS_GUIDELINES,
    CUSTOM_TOOLS_NOTE,
    GUIDELINE_BASH_ONLY,
    GUIDELINE_PREFER_NATIVE_EXPLORERS,
    GUIDELINES_HEADER,
    KB_BLOCK,
    PROJECT_CONTEXT_CLOSE,
    PROJECT_CONTEXT_OPEN,
    PROJECT_INSTRUCTIONS_TEMPLATE,
    ROLE_LINE,
    SKILLS_FALLBACK_BLOCK,
    SKILLS_XML_PREAMBLE,
)
from src.agents.slo_agent.skills_loader import SkillEntryDAO
```

**Updated `invoke()` signature (BEFORE):**

```python
# slo/src/agents/slo_agent/prompts/__init__.py  [BEFORE — invoke()]

@classmethod
def invoke(
    cls,
    *,
    tools: Optional[Sequence[BaseTool]] = None,
    cwd: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    append_system_prompt: Optional[str] = None,
    project_context_files: Optional[list[tuple[str, str]]] = None,
) -> str:
```

**Updated `invoke()` signature and skills section assembly (AFTER):**

```python
# slo/src/agents/slo_agent/prompts/__init__.py  [AFTER — invoke()]

@classmethod
def invoke(
    cls,
    *,
    tools: Optional[Sequence[BaseTool]] = None,
    cwd: Optional[str] = None,
    custom_prompt: Optional[str] = None,
    append_system_prompt: Optional[str] = None,
    project_context_files: Optional[list[tuple[str, str]]] = None,
    skills: Optional[list[SkillEntryDAO]] = None,
) -> str:
    """Build the final system prompt for the current session.

    Args:
        tools (Optional[Sequence[BaseTool]], optional): Active tools bound to
            the agent. Defaults to None.
        cwd (Optional[str], optional): Working directory to surface at the
            end of the prompt. Defaults to None.
        custom_prompt (Optional[str], optional): Full prompt body that
            replaces the standard role/tools/guidelines body. Defaults to None.
        append_system_prompt (Optional[str], optional): Extra text appended
            after the default or custom prompt body. Defaults to None.
        project_context_files (Optional[list[tuple[str, str]]], optional):
            Discovered project guidance files as ``(path, content)`` pairs.
            Defaults to None.
        skills (Optional[list[SkillEntryDAO]], optional): Skill entries loaded
            by ``SkillsLoader.load()`` at agent construction. When provided
            and non-empty, the skills block renders as a structured XML block
            instead of the INDEX.md-pointer prose. When ``None`` or ``[]``,
            falls back to the INDEX.md-pointer prose. Defaults to None.

    Returns:
        str: The fully assembled system prompt.
    """
    resolved_tools: Sequence[BaseTool] = tools or ()
    resolved_project_context_files: list[tuple[str, str]] = list(project_context_files or [])
    resolved_cwd: Optional[str] = cls._resolve_cwd(cwd=cwd)
    resolved_skills: list[SkillEntryDAO] = skills or []

    log_info(
        msg="SystemPromptBuilder.invoke",
        tools_count=len(resolved_tools),
        has_custom_prompt=custom_prompt is not None,
        has_append_prompt=bool(append_system_prompt and append_system_prompt.strip()),
        has_project_context=bool(resolved_project_context_files),
        skills_count=len(resolved_skills),
    )

    if custom_prompt is not None:
        return cls._assemble_custom_prompt(
            custom_prompt=custom_prompt,
            append_system_prompt=append_system_prompt,
            project_context_files=resolved_project_context_files,
            cwd=resolved_cwd,
        )

    sections: list[str] = [
        cls._build_role_line(),
        cls._build_tools_block(tools=resolved_tools),
        cls._build_custom_tools_note(),
        cls._build_guidelines_block(tools=resolved_tools),
        cls._build_skills_block(skills=resolved_skills),
        cls._build_knowledge_base_block(),
        cls._build_append_block(append_system_prompt=append_system_prompt),
        cls._build_project_context_block(
            project_context_files=resolved_project_context_files,
        ),
        cls._build_date_line(),
        cls._build_cwd_line(cwd=resolved_cwd),
    ]
    return "\n\n".join(section for section in sections if section)
```

**`_build_skills_block` — BEFORE:**

```python
# slo/src/agents/slo_agent/prompts/__init__.py  [BEFORE — _build_skills_block]

@classmethod
def _build_skills_block(cls) -> str:
    """Return the skills guidance block.

    Returns:
        str: The rendered skills block with the absolute path to
            ``skills/INDEX.md`` interpolated.
    """
    skills_index_path: str = os.path.join(SKILLS_DIR, "INDEX.md")
    return SKILLS_BLOCK_TEMPLATE.format(
        skills_index_path=skills_index_path,
    ).strip()
```

**`_build_skills_block` — AFTER (with new `_format_skills_as_xml` and `_escape_xml` helpers):**

```python
# slo/src/agents/slo_agent/prompts/__init__.py  [AFTER — _build_skills_block + helpers]

@classmethod
def _build_skills_block(cls, *, skills: list[SkillEntryDAO]) -> str:
    """Render the skills section of the system prompt.

    When ``skills`` is non-empty, renders the Pi-format structured XML block
    so skill names and locations are visible to the model without a read-tool
    call. When ``skills`` is empty (``SKILLS_DIR`` missing or unreadable),
    falls back to the INDEX.md-pointer prose retained in
    ``SKILLS_FALLBACK_BLOCK``.

    ``invoke()`` calls this as part of the standard sections assembly; the
    ``skills`` argument comes from ``SkillsLoader.load()`` called during
    ``SloAgent.__init__``. The ``invoke()`` caller normalizes ``None`` to
    ``[]`` before passing it here, so this method only ever sees a list.

    Args:
        skills (list[SkillEntryDAO]): Loaded and filtered skill entries. Pass
            an empty list to trigger the INDEX.md fallback.

    Returns:
        str: The rendered skills block.
    """
    if not skills:
        skills_index_path: str = os.path.join(SKILLS_DIR, "INDEX.md")
        return SKILLS_FALLBACK_BLOCK.format(
            skills_index_path=skills_index_path,
        ).strip()
    return cls._format_skills_as_xml(skills=skills)

@classmethod
def _format_skills_as_xml(cls, *, skills: list[SkillEntryDAO]) -> str:
    """Render a list of skill entries as the Pi-format XML block.

    Produces the exact block format used by Pi's ``formatSkillsForPrompt()``
    in ``pi/packages/coding-agent/src/core/skills.ts``. The output is static
    for the lifetime of a session (skills do not change mid-session) and is
    therefore a stable prompt-cache target.

    ``_build_skills_block()`` calls this when the skills list is non-empty.
    The block opens with ``SKILLS_XML_PREAMBLE`` (three instructional lines)
    followed by the ``<available_skills>`` wrapper and one ``<skill>`` element
    per entry. All text values are XML-escaped.

    Args:
        skills (list[SkillEntryDAO]): Non-empty list of skill entries to
            render. Caller guarantees non-empty; passing an empty list
            produces a structurally valid but empty XML block.

    Returns:
        str: The fully rendered XML skills block.
    """
    skill_elements: list[str] = []
    entry: SkillEntryDAO
    for entry in skills:
        skill_elements.append(
            "  <skill>\n"
            f"    <name>{cls._escape_xml(text=entry.name)}</name>\n"
            f"    <description>{cls._escape_xml(text=entry.description)}</description>\n"
            f"    <location>{cls._escape_xml(text=entry.file_path)}</location>\n"
            "  </skill>"
        )

    inner: str = "\n".join(skill_elements)
    return (
        f"{SKILLS_XML_PREAMBLE}\n\n"
        f"<available_skills>\n"
        f"{inner}\n"
        f"</available_skills>"
    )

@classmethod
def _escape_xml(cls, *, text: str) -> str:
    """Escape the five XML-special characters in ``text``.

    Applied to every value embedded in an XML attribute or element by
    ``_format_skills_as_xml()``. The five substitutions match Pi's
    ``escapeXml()`` helper, applied in this order to avoid double-escaping.

    Args:
        text (str): Raw string value to escape.

    Returns:
        str: XML-safe string with ``&``, ``<``, ``>``, ``"``, and ``'``
            replaced by their entity references.
    """
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
```

Note: the `os` import is already present in `prompts/__init__.py`. No new import is needed there.

### Step 4 — `agent.py` changes

`SloAgent.__init__` acquires one new call and threads `skills` through two more methods.

**Updated `__init__` body (BEFORE — lines 146–172):**

```python
# slo/src/agents/slo_agent/agent.py  [BEFORE — relevant __init__ lines]

        self._graph: CompiledStateGraph = build_slo_agent(
            model_name=model_name,
            tools=tools,
            llm=llm,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )
        self._cwd: str = cwd if cwd is not None else os.getcwd()
        self._project_context_files: list[tuple[str, str]] = ProjectContextDiscovery.invoke(cwd=self._cwd)
        self._system_prompt: str = self._resolve_system_prompt(
            system_prompt=system_prompt,
            tools=tools,
            cwd=self._cwd,
            append_system_prompt=append_system_prompt,
            custom_prompt=custom_prompt,
            project_context_files=self._project_context_files,
        )
```

**Updated `__init__` body (AFTER):**

```python
# slo/src/agents/slo_agent/agent.py  [AFTER — relevant __init__ lines]

        self._graph: CompiledStateGraph = build_slo_agent(
            model_name=model_name,
            tools=tools,
            llm=llm,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )
        self._cwd: str = cwd if cwd is not None else os.getcwd()
        self._project_context_files: list[tuple[str, str]] = ProjectContextDiscovery.invoke(
            cwd=self._cwd,
        )
        self._skills: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=SKILLS_DIR,
        )
        self._system_prompt: str = self._resolve_system_prompt(
            system_prompt=system_prompt,
            tools=tools,
            cwd=self._cwd,
            append_system_prompt=append_system_prompt,
            custom_prompt=custom_prompt,
            project_context_files=self._project_context_files,
            skills=self._skills,
        )
```

**Updated `_resolve_system_prompt` (BEFORE):**

```python
# slo/src/agents/slo_agent/agent.py  [BEFORE — _resolve_system_prompt]

    def _resolve_system_prompt(
        self,
        *,
        system_prompt: Optional[str],
        tools: Optional[Sequence[BaseTool]],
        cwd: str,
        append_system_prompt: Optional[str],
        custom_prompt: Optional[str],
        project_context_files: list[tuple[str, str]],
    ) -> str:
        if system_prompt is not None:
            return system_prompt

        return SystemPromptBuilder.invoke(
            tools=tools,
            cwd=cwd,
            custom_prompt=custom_prompt,
            append_system_prompt=append_system_prompt,
            project_context_files=project_context_files,
        )
```

**Updated `_resolve_system_prompt` (AFTER):**

```python
# slo/src/agents/slo_agent/agent.py  [AFTER — _resolve_system_prompt]

    def _resolve_system_prompt(
        self,
        *,
        system_prompt: Optional[str],
        tools: Optional[Sequence[BaseTool]],
        cwd: str,
        append_system_prompt: Optional[str],
        custom_prompt: Optional[str],
        project_context_files: list[tuple[str, str]],
        skills: list[SkillEntryDAO],
    ) -> str:
        """Choose between caller override and runtime prompt assembly.

        ``__init__`` invokes this once during agent construction after cwd,
        project-context discovery, and skills loading have already completed.
        In the common case it delegates to ``SystemPromptBuilder.invoke()``;
        when the caller has supplied a final ``system_prompt`` string it
        returns that value unchanged and bypasses runtime assembly entirely.

        Args:
            system_prompt (Optional[str]): Caller-supplied final prompt.
                Highest-precedence override.
            tools (Optional[Sequence[BaseTool]]): Active tools for this run.
            cwd (str): Working directory for this run.
            append_system_prompt (Optional[str]): Optional prompt text to
                append on the runtime-assembly path.
            custom_prompt (Optional[str]): Optional full body override on
                the runtime-assembly path.
            project_context_files (list[tuple[str, str]]): Discovered repo
                guidance files as ``(path, content)`` pairs.
            skills (list[SkillEntryDAO]): Skill entries loaded by
                ``SkillsLoader.load()`` at construction time.

        Returns:
            str: The prompt string stored on the agent instance.
        """
        if system_prompt is not None:
            return system_prompt

        return SystemPromptBuilder.invoke(
            tools=tools,
            cwd=cwd,
            custom_prompt=custom_prompt,
            append_system_prompt=append_system_prompt,
            project_context_files=project_context_files,
            skills=skills,
        )
```

The new import lines needed at the top of `agent.py`:

```python
# slo/src/agents/slo_agent/agent.py  [NEW imports]

from config.cfg import SKILLS_DIR
from src.agents.slo_agent.skills_loader import SkillEntryDAO, SkillsLoader
```

---

## 8. Tests

### New test file: `slo/tests/agents/slo_agent/test_skills_loader.py`

```python
# slo/tests/agents/slo_agent/test_skills_loader.py

"""Tests for SkillsLoader and SkillEntryDAO (sub-spec 19)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.skills_loader import SkillEntryDAO, SkillsLoader


def _write_skill(
    directory: Path,
    *,
    name: str = "my-skill",
    description: str = "Does something useful.",
    extra_frontmatter: str = "",
) -> Path:
    """Write a minimal valid SKILL.md into ``directory`` and return its path.

    Args:
        directory (Path): Directory in which to create ``SKILL.md``.
        name (str): Value for the frontmatter ``name`` key. Defaults to
            ``"my-skill"``.
        description (str): Value for the frontmatter ``description`` key.
            Defaults to ``"Does something useful."``.
        extra_frontmatter (str): Additional YAML lines to append inside the
            frontmatter block. Defaults to empty string.

    Returns:
        Path: Absolute path to the created SKILL.md file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    content: str = (
        f"---\nname: {name}\ndescription: {description}\n"
        f"{extra_frontmatter}\n---\n\n# Body text\n"
    )
    skill_file: Path = directory / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


class TestSkillsLoaderParsesFullFrontmatter:
    """Happy-path parsing: name, description, and file_path are captured."""

    def test_returns_entry_with_correct_name_and_description(
        self,
        tmp_path: Path,
    ) -> None:
        """A valid SKILL.md produces a SkillEntryDAO with correct name and description."""
        skill_dir: Path = tmp_path / "coding" / "build-routers"
        _write_skill(
            skill_dir,
            name="build-routers",
            description="Adding or modifying FastAPI endpoints.",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "build-routers"
        assert entries[0].description == "Adding or modifying FastAPI endpoints."
        assert entries[0].file_path == str((skill_dir / "SKILL.md").resolve())
        assert entries[0].disable_model_invocation is False

    def test_falls_back_to_parent_dir_name_when_name_key_absent(
        self,
        tmp_path: Path,
    ) -> None:
        """When ``name`` is missing from frontmatter, the parent directory name is used."""
        skill_dir: Path = tmp_path / "coding" / "my-special-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: Does something.\n---\n\n# Body\n",
            encoding="utf-8",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "my-special-skill"

    def test_returns_multiple_entries_for_multiple_skill_files(
        self,
        tmp_path: Path,
    ) -> None:
        """Multiple SKILL.md files in a tree all produce separate entries."""
        _write_skill(tmp_path / "coding" / "skill-a", name="skill-a", description="A.")
        _write_skill(tmp_path / "coding" / "skill-b", name="skill-b", description="B.")
        _write_skill(tmp_path / "git-ops" / "skill-c", name="skill-c", description="C.")

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 3
        names: set[str] = {e.name for e in entries}
        assert names == {"skill-a", "skill-b", "skill-c"}


class TestSkillsLoaderSkipsDisableModelInvocation:
    """Skills with disable-model-invocation: true are excluded from the result."""

    def test_skill_with_disable_flag_is_excluded(
        self,
        tmp_path: Path,
    ) -> None:
        """A SKILL.md with ``disable-model-invocation: true`` is not returned."""
        _write_skill(
            tmp_path / "meta" / "internal-skill",
            name="internal-skill",
            description="Internal use only.",
            extra_frontmatter="disable-model-invocation: true",
        )
        _write_skill(
            tmp_path / "coding" / "visible-skill",
            name="visible-skill",
            description="Visible to model.",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "visible-skill"

    def test_skill_with_disable_flag_false_is_included(
        self,
        tmp_path: Path,
    ) -> None:
        """A SKILL.md with ``disable-model-invocation: false`` is included normally."""
        _write_skill(
            tmp_path / "coding" / "normal-skill",
            name="normal-skill",
            description="Normal skill.",
            extra_frontmatter="disable-model-invocation: false",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "normal-skill"


class TestSkillsLoaderFallsBackGracefullyOnMalformedYaml:
    """Malformed or incomplete SKILL.md files are skipped without raising."""

    def test_skill_without_description_is_excluded(
        self,
        tmp_path: Path,
    ) -> None:
        """A SKILL.md with no ``description`` key is skipped; others are returned."""
        skill_dir: Path = tmp_path / "coding" / "no-description"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: no-description\n---\n\n# Body\n",
            encoding="utf-8",
        )
        _write_skill(
            tmp_path / "coding" / "has-description",
            name="has-description",
            description="This one is fine.",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "has-description"

    def test_skill_with_invalid_yaml_is_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        """A SKILL.md with invalid YAML in its frontmatter is skipped; others are not."""
        bad_dir: Path = tmp_path / "coding" / "bad-yaml"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text(
            "---\n: this is invalid yaml: [\n---\n\n# Body\n",
            encoding="utf-8",
        )
        _write_skill(
            tmp_path / "coding" / "good-skill",
            name="good-skill",
            description="This parses fine.",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "good-skill"

    def test_skill_with_no_frontmatter_is_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        """A SKILL.md that starts with body text (no ``---`` opener) is skipped."""
        no_fm_dir: Path = tmp_path / "coding" / "no-frontmatter"
        no_fm_dir.mkdir(parents=True)
        (no_fm_dir / "SKILL.md").write_text(
            "# No frontmatter here\n\nJust body text.\n",
            encoding="utf-8",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert entries == []

    def test_skill_with_non_dict_yaml_is_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        """A SKILL.md whose frontmatter parses to a non-dict value is skipped.

        This covers the ``if not isinstance(parsed, dict)`` guard in
        ``_extract_frontmatter``. A bare YAML scalar (e.g. a plain string)
        is syntactically valid but not a mapping, so it must be treated as
        malformed and skipped.
        """
        non_dict_dir: Path = tmp_path / "coding" / "non-dict-yaml"
        non_dict_dir.mkdir(parents=True)
        (non_dict_dir / "SKILL.md").write_text(
            "---\njust a bare string value\n---\n\n# Body\n",
            encoding="utf-8",
        )
        _write_skill(
            tmp_path / "coding" / "good-skill",
            name="good-skill",
            description="This parses fine.",
        )

        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path),
        )

        assert len(entries) == 1
        assert entries[0].name == "good-skill"

    def test_unreadable_skill_file_is_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        """An OSError on read_text() causes the file to be skipped; others are returned.

        This covers the ``except OSError`` guard in ``_parse_skill_file``.
        We patch ``Path.read_text`` on the specific file that should fail so
        the other file is unaffected.
        """
        bad_dir: Path = tmp_path / "coding" / "unreadable"
        bad_dir.mkdir(parents=True)
        bad_skill_file: Path = bad_dir / "SKILL.md"
        bad_skill_file.write_text("---\nname: unreadable\ndescription: x\n---\n", encoding="utf-8")

        good_dir: Path = tmp_path / "coding" / "readable"
        _write_skill(
            good_dir,
            name="readable-skill",
            description="This one loads fine.",
        )

        original_read_text = Path.read_text

        def _patched_read_text(self: Path, **kwargs: object) -> str:
            if self == bad_skill_file.resolve():
                raise OSError("Permission denied")
            return original_read_text(self, **kwargs)

        with patch.object(Path, "read_text", _patched_read_text):
            entries: list[SkillEntryDAO] = SkillsLoader.load(
                skills_dir=str(tmp_path),
            )

        assert len(entries) == 1
        assert entries[0].name == "readable-skill"

    def test_nonexistent_skills_dir_returns_empty_list(
        self,
        tmp_path: Path,
    ) -> None:
        """A path that does not exist returns an empty list instead of raising."""
        entries: list[SkillEntryDAO] = SkillsLoader.load(
            skills_dir=str(tmp_path / "does_not_exist"),
        )
        assert entries == []
```

### Updates to `slo/tests/agents/slo_agent/test_prompts.py`

Three existing tests in `TestSystemPromptBuilder` break because they assert on text
that lives in the removed `SKILLS_BLOCK_TEMPLATE`. The table below shows each test,
what it currently asserts, and what the updated assertion should be.

| Test | Current assertion (breaks) | New assertion |
|---|---|---|
| `test_invoke_points_at_skills_index` | `"skills/INDEX.md" in prompt` and `"## Skills" in prompt` | `"<available_skills>" in prompt` (XML block now present) |
| `test_skills_index_path_is_absolute` | `os.path.join(SKILLS_DIR, "INDEX.md") in prompt` | `SKILLS_DIR in prompt` (at least one `<location>` contains the skills dir) |
| `test_invoke_advertises_both_coding_and_analysis_skills` | `"Coding-convention skills" in prompt` | Check for `"<available_skills>" in prompt` or an actual skill name from the live tree |

Three new tests for the XML prompt shape belong in `TestSystemPromptBuilderInvoke` in `test_prompts.py`:

```python
# slo/tests/agents/slo_agent/test_prompts.py  [NEW tests]

def test_system_prompt_contains_available_skills_xml_when_skills_loaded(
    self,
) -> None:
    """When skills are passed to invoke(), the prompt contains the XML block."""
    entries: list[SkillEntryDAO] = [
        SkillEntryDAO(
            name="build-routers",
            description="Adding or modifying FastAPI endpoints.",
            file_path="/abs/skills/coding/build-routers/SKILL.md",
        ),
        SkillEntryDAO(
            name="commit-and-push",
            description="Stage and commit files safely.",
            file_path="/abs/skills/git-ops/commit-and-push/SKILL.md",
        ),
    ]

    prompt: str = SystemPromptBuilder.invoke(skills=entries)

    assert "<available_skills>" in prompt
    assert "</available_skills>" in prompt
    assert "<name>build-routers</name>" in prompt
    assert "<description>Adding or modifying FastAPI endpoints.</description>" in prompt
    assert "<location>/abs/skills/coding/build-routers/SKILL.md</location>" in prompt
    assert "<name>commit-and-push</name>" in prompt

def test_system_prompt_falls_back_to_index_md_pointer_when_skills_empty_list(
    self,
) -> None:
    """When skills=[] is passed, the prompt falls back to the INDEX.md-pointer prose."""
    prompt: str = SystemPromptBuilder.invoke(skills=[])

    assert "<available_skills>" not in prompt
    assert "INDEX.md" in prompt

def test_system_prompt_falls_back_to_index_md_pointer_when_skills_none(
    self,
) -> None:
    """When skills=None (default) is passed, the prompt falls back identically to skills=[].

    This verifies backward compatibility: callers that do not supply the
    ``skills`` keyword (e.g. existing tests, SYSTEM_PROMPT module constant)
    still receive the INDEX.md-pointer prose rather than an error or an
    empty XML block.
    """
    prompt_none: str = SystemPromptBuilder.invoke(skills=None)
    prompt_empty: str = SystemPromptBuilder.invoke(skills=[])

    assert prompt_none == prompt_empty
    assert "<available_skills>" not in prompt_none
    assert "INDEX.md" in prompt_none

def test_xml_escaping_applied_to_special_characters_in_skill_fields(
    self,
) -> None:
    """Skill names/descriptions containing XML-special chars are escaped in the block."""
    entries: list[SkillEntryDAO] = [
        SkillEntryDAO(
            name="skill-with-<special>&chars",
            description='Handles "quoted" & <tagged> text.',
            file_path="/abs/skills/special/SKILL.md",
        ),
    ]

    prompt: str = SystemPromptBuilder.invoke(skills=entries)

    assert "&lt;special&gt;" in prompt
    assert "&amp;chars" in prompt
    assert "&quot;quoted&quot;" in prompt
    assert "&amp;" in prompt
```

### Verification commands

Run only the new + affected tests first to get fast feedback:

```bash
cd "$SLO_APP_DIR"
PYTHONPATH=${PWD} python -m pytest -sv tests/agents/slo_agent/test_skills_loader.py
PYTHONPATH=${PWD} python -m pytest -sv tests/agents/slo_agent/test_prompts.py
```

Full suite to confirm no regressions:

```bash
PYTHONPATH=${PWD} python -m pytest -sv tests/
```

### Manual smoke check

```bash
cd "$SLO_APP_DIR"
python -c "
from src.agents.slo_agent.prompts import SystemPromptBuilder
from src.agents.slo_agent.skills_loader import SkillsLoader
from config.cfg import SKILLS_DIR

skills = SkillsLoader.load(skills_dir=SKILLS_DIR)
print(f'Loaded {len(skills)} skills')

prompt = SystemPromptBuilder.invoke(skills=skills)
start = prompt.index('<available_skills>')
end = prompt.index('</available_skills>') + len('</available_skills>')
print(prompt[start:end][:800])
"
```

Expected output: skill count, then the first few hundred characters of the XML block showing `<name>`, `<description>`, and `<location>` elements.

---

## 9. Acceptance Criteria

All criteria are mechanically verifiable.

1. `SkillsLoader.load(skills_dir=SKILLS_DIR)` returns a non-empty `list[SkillEntryDAO]` when called against the committed `slo/skills/` tree. Running `python -c "from src.agents.slo_agent.skills_loader import SkillsLoader; from config.cfg import SKILLS_DIR; r = SkillsLoader.load(skills_dir=SKILLS_DIR); assert len(r) > 50, r"` exits with code 0.

2. `SystemPromptBuilder.invoke(skills=entries)` where `entries` is the list from criterion 1 produces a string containing `<available_skills>` and `</available_skills>`.

3. `SystemPromptBuilder.invoke(skills=[])` produces a string containing `"INDEX.md"` and not containing `"<available_skills>"`.

4. `SystemPromptBuilder.invoke(skills=None)` (no argument / explicit None) produces the same result as criterion 3 (backward-compatible default). Verified by `assert SystemPromptBuilder.invoke(skills=None) == SystemPromptBuilder.invoke(skills=[])`.

5. A `SKILL.md` whose frontmatter contains `disable-model-invocation: true` does not appear in the `<available_skills>` block. Verified by the `test_skill_with_disable_flag_is_excluded` test.

6. A `SKILL.md` with invalid YAML in its frontmatter does not raise an exception from `SkillsLoader.load()`. Verified by the `test_skill_with_invalid_yaml_is_skipped` test.

7. A `SKILL.md` with no `description` key does not appear in the result of `SkillsLoader.load()`. Verified by the `test_skill_without_description_is_excluded` test.

8. The `<location>` values in the XML block are absolute paths (start with `/` on Unix). Verified by asserting `all(e.file_path.startswith("/") for e in entries)` after `SkillsLoader.load()`.

9. All eight tests in `test_skills_loader.py` pass. `python -m pytest -sv tests/agents/slo_agent/test_skills_loader.py` exits with code 0.

10. All tests in `test_prompts.py` pass after the three updated assertions and three new tests are applied. `python -m pytest -sv tests/agents/slo_agent/test_prompts.py` exits with code 0.

11. The full test suite passes. `python -m pytest tests/` exits with code 0.

12. `SloAgent(cwd="/tmp")` can be constructed without error in a test environment (using a `FauxChatModel`). The `_system_prompt` attribute contains `<available_skills>` when `SKILLS_DIR` points to the committed skills tree.

---

## 10. Dependencies

**Blocked by:** None. This slice has no upstream code dependency on any pending spec. It modifies only the system prompt assembly pipeline, which no other in-flight feature touches.

**Blocks downstream:**

- Any future sub-spec that adds new skills categories or per-skill prompt-injection behavior should read this spec first — the `SkillEntryDAO` model is the authoritative data contract for skill metadata as seen by the prompt layer.
- The prompt-cache optimization work (if/when a formal sub-spec is written for Anthropic cache-write headers) should treat the `<available_skills>` block as a primary cache anchor. The block is static within a session and positioned early enough in the assembled prompt to be covered by Anthropic's 1024-token minimum cache granule at current skill counts.
- `specifications/18-system-prompt-analysis-and-pi-parity.md` tracks this slice as a key gap to close. Mark this item resolved in that document once criterion 2 is verified.

**Runtime dependency:** PyYAML. Already present as a transitive dependency via LangChain (`langchain-core` → `pyyaml`). Verified with `python -c "import yaml"`. No new entry in `pyproject.toml` required.
