"""Behavioural tests for ``SystemPromptBuilder``.

Two layers of coverage:

* ``TestSystemPromptBuilder`` keeps the legacy default-body wording checks
  (role line, always-on guidelines, skills index pointer, knowledge base
  pointer). These still hold against the no-argument default prompt.
* ``TestSystemPromptBuilderInvoke`` covers the runtime assembly branches the
  02.a builder introduced: custom prompt override, append handling, tool
  snippet rendering, guideline selection, project context wrapping, cwd
  rendering/normalization, and the ISO date line.

The builder is a pure function: it never touches the network or the
filesystem (it reads only ``SKILLS_DIR`` / ``SLO_KB_DIR`` wording and computes
``date.today()``), so every test here is deterministic and isolated.
"""

from __future__ import annotations

import os
import re

from langchain_core.tools import BaseTool, tool

from config.cfg import SKILLS_DIR
from src.agents.slo_agent.project_context.dao import ContextFileEntryDAO
from src.agents.slo_agent.prompts import SystemPromptBuilder
from src.agents.slo_agent.prompts.system_prompt import PROJECT_INSTRUCTIONS_TEMPLATE
from src.agents.slo_agent.skills.dao import SkillEntryDAO
from src.agents.slo_agent.workspace.dao import WorkspaceFolderDAO
from src.agents.tools.read import READ_PROMPT_SNIPPET


def _make_tool(name: str) -> BaseTool:
    """Build a no-op LangChain tool whose registered name is ``name``.

    The ``@tool`` decorator names the tool after the wrapped function, so this
    helper dynamically renames the function before decorating. Used to fabricate
    toolsets ("bash", "grep", "mystery_tool", ...) for branch coverage without
    importing the real tool modules.

    Args:
        name (str): The desired ``BaseTool.name``.

    Returns:
        BaseTool: A LangChain tool registered under ``name``.
    """

    def _fn(arg: str) -> str:
        """No-op tool body used only for prompt-rendering tests."""
        return ""

    _fn.__name__ = name
    _fn.__doc__ = f"Stub {name} tool for prompt rendering tests."
    return tool(_fn)


class TestSystemPromptBuilder:
    """Default-body wording checks against the no-argument prompt."""

    def test_invoke_includes_role_statement(self) -> None:
        """The default body opens with the slo role/identity line."""
        assert "expert coding assistant operating inside slo" in SystemPromptBuilder.invoke()

    def test_invoke_includes_always_guidelines(self) -> None:
        """The always-on guideline bullets appear in the default body."""
        prompt: str = SystemPromptBuilder.invoke()
        assert "Be concise in your responses" in prompt
        assert "Show file paths clearly when working with files" in prompt

    def test_invoke_points_at_skills_index(self) -> None:
        """The prompt tells the agent where the skills index lives."""
        prompt: str = SystemPromptBuilder.invoke()
        assert "skills/INDEX.md" in prompt
        assert "## Skills" in prompt

    def test_skills_index_path_is_absolute(self) -> None:
        """The skills/INDEX.md reference is an absolute path (01.n §5.5)."""
        prompt: str = SystemPromptBuilder.invoke()
        assert os.path.join(SKILLS_DIR, "INDEX.md") in prompt
        assert SKILLS_DIR.startswith(os.sep)

    def test_invoke_advertises_both_coding_and_analysis_skills(self) -> None:
        """The prompt signals skills cover analytical/workflow work, not only coding.

        Per the 02.a.1 decision the shipped ``SKILLS_BLOCK_TEMPLATE`` carries the
        existing fuller wording verbatim, which contains the literal strings
        ``"Coding-convention skills"`` and ``"Analysis and workflow skills"``.
        """
        prompt: str = SystemPromptBuilder.invoke()
        assert "Coding-convention skills" in prompt or "coding-convention" in prompt.lower()
        assert "Analysis and workflow skills" in prompt or "analysis" in prompt.lower()

    def test_invoke_points_at_knowledge_base(self) -> None:
        """The prompt tells the agent how to reach the knowledge base."""
        prompt: str = SystemPromptBuilder.invoke()
        assert "## Knowledge Base" in prompt
        assert "SLO_KB_DIR" in prompt
        assert "Home.md" in prompt


class TestSystemPromptBuilderInvoke:
    """Branch-by-branch behavioral tests for runtime system-prompt assembly."""

    # --- branch 1: parameterless invoke() is idempotent ---
    def test_returns_same_prompt_when_called_without_kwargs_twice(self) -> None:
        """Calling invoke() with no args produces the same output each time."""
        assert SystemPromptBuilder.invoke() == SystemPromptBuilder.invoke()

    # --- branch 2: custom prompt replaces the default body ---
    def test_custom_prompt_replaces_default_body_when_supplied(self) -> None:
        """A custom prompt becomes the body and the default body is omitted."""
        prompt: str = SystemPromptBuilder.invoke(
            custom_prompt="You are a focused review agent.",
            tools=[_make_tool(name="read")],
            cwd="/tmp/spec-review",
        )

        # custom body leads the prompt
        assert prompt.startswith("You are a focused review agent.")
        # default-body sections are gone, even though a tool was passed
        assert "expert coding assistant operating inside slo" not in prompt
        assert "Available tools:" not in prompt
        assert "Guidelines:" not in prompt
        # runtime grounding still appears
        assert "Current working directory: /tmp/spec-review" in prompt

    # --- branch 3: append_system_prompt blank ignored / non-empty appears after body ---
    def test_append_prompt_is_ignored_when_blank_or_whitespace(self) -> None:
        """Blank or whitespace-only append text is dropped, matching the default body."""
        baseline: str = SystemPromptBuilder.invoke()
        for blank in ("", "   ", "\n\t  \n"):
            assert SystemPromptBuilder.invoke(append_system_prompt=blank) == baseline

    def test_append_prompt_appears_after_body_when_non_empty(self) -> None:
        """Non-empty append text is appended (trimmed) after the default body."""
        marker: str = "Extra house rule: prefer ripgrep."
        prompt: str = SystemPromptBuilder.invoke(append_system_prompt=f"  {marker}  ")

        assert marker in prompt
        # appears after the role line (i.e. after the body, not as a replacement)
        assert prompt.index(marker) > prompt.index("expert coding assistant operating inside slo")
        # leading/trailing whitespace was stripped
        assert f"  {marker}  " not in prompt

    # --- branch 4: tools WITH registered snippets render under "Available tools:" ---
    def test_renders_registered_tool_snippet_when_tool_is_supplied(self) -> None:
        """Render prompt-facing tool descriptions for registered tools."""
        prompt: str = SystemPromptBuilder.invoke(tools=[_make_tool(name="read")])

        assert "Available tools:" in prompt
        assert f"- read: {READ_PROMPT_SNIPPET}" in prompt

    # --- branch 5: tools WITHOUT registered snippets are skipped ---
    def test_skips_tool_without_registered_snippet(self) -> None:
        """A tool with no entry in TOOL_PROMPT_SNIPPETS is omitted from the list."""
        prompt: str = SystemPromptBuilder.invoke(
            tools=[_make_tool(name="read"), _make_tool(name="mystery_tool")],
        )

        # registered tool is listed
        assert f"- read: {READ_PROMPT_SNIPPET}" in prompt
        # unregistered tool is silently skipped
        assert "mystery_tool" not in prompt

    # --- branch 6: bash-only toolset -> bash exploration guideline ---
    def test_bash_only_toolset_emits_bash_exploration_guideline(self) -> None:
        """bash present, no native explorers -> 'Use bash for file operations'."""
        prompt: str = SystemPromptBuilder.invoke(tools=[_make_tool(name="bash")])

        assert "Use bash for file operations like ls, rg, find" in prompt
        assert "Prefer grep/find/ls tools over bash" not in prompt

    # --- branch 7: bash + grep/find/ls -> prefer-native-explorers guideline ---
    def test_bash_with_native_explorers_emits_prefer_native_guideline(self) -> None:
        """bash present alongside grep/find/ls -> prefer the native tools."""
        prompt: str = SystemPromptBuilder.invoke(
            tools=[
                _make_tool(name="bash"),
                _make_tool(name="grep"),
                _make_tool(name="find"),
                _make_tool(name="ls"),
            ],
        )

        assert (
            "Prefer grep/find/ls tools over bash for file exploration "
            "(faster, respects .gitignore)" in prompt
        )
        assert "Use bash for file operations like ls, rg, find" not in prompt

    # --- branch 8: write present -> inline-content guideline ---
    def test_write_tool_emits_inline_content_guideline(self) -> None:
        """write present -> model is told to pass content inline in the tool call."""
        prompt: str = SystemPromptBuilder.invoke(tools=[_make_tool(name="write")])

        assert "Always pass the complete file content as the content argument directly in the write" in prompt
        assert "do not output file content as text and then call write with only a path" in prompt

    def test_write_guideline_absent_without_write_tool(self) -> None:
        """The inline-content guideline is NOT injected when write is not in the toolset."""
        prompt: str = SystemPromptBuilder.invoke(tools=[_make_tool(name="read"), _make_tool(name="bash")])

        assert "content argument directly in the write" not in prompt

    # --- branch 9: project context wrapped in <project_context>/<project_instructions> ---
    def test_wraps_project_context_files_in_tags(self) -> None:
        """Discovered project files render inside the XML-style context tags."""
        files: list[ContextFileEntryDAO] = [
            ContextFileEntryDAO(
                path="/abs/path/SLO.md",
                content="Use make test before changing code.",
                tier="project",
            ),
            ContextFileEntryDAO(
                path="/abs/path/AGENTS.md",
                content="Read docs/RESEARCH.md before editing routers.",
                tier="project",
            ),
        ]
        prompt: str = SystemPromptBuilder.invoke(project_context_files=files)

        assert "<project_context>" in prompt
        assert "</project_context>" in prompt
        # exact per-file rendering matches PROJECT_INSTRUCTIONS_TEMPLATE
        for entry in files:
            expected: str = PROJECT_INSTRUCTIONS_TEMPLATE.format(path=entry.path, content=entry.content)
            assert expected in prompt

    def test_global_tier_entries_render_before_project_tier(self) -> None:
        """Global-tier entries appear before project-tier entries in the context block."""
        files: list[ContextFileEntryDAO] = [
            ContextFileEntryDAO(
                path="/home/user/.slo/AGENTS.md",
                content="global user rules",
                tier="global",
            ),
            ContextFileEntryDAO(
                path="/abs/path/SLO.md",
                content="project rules",
                tier="project",
            ),
        ]
        prompt: str = SystemPromptBuilder.invoke(project_context_files=files)

        global_pos = prompt.index("global user rules")
        project_pos = prompt.index("project rules")
        assert global_pos < project_pos, "Global-tier content must appear before project-tier content"

    def test_omits_project_context_block_when_no_files(self) -> None:
        """No discovered files -> no project_context wrapper at all."""
        prompt: str = SystemPromptBuilder.invoke(project_context_files=[])
        assert "<project_context>" not in prompt

    def test_workspace_tier_entry_renders_inside_project_context(self) -> None:
        """Workspace-tier entries render like any other project instruction block."""
        files: list[ContextFileEntryDAO] = [
            ContextFileEntryDAO(
                path="/abs/workspace/AGENTS.md",
                content="workspace rules",
                tier="workspace_folder",
                workspace_folder_root="/abs/workspace",
                workspace_folder_display_name="Workspace",
            ),
        ]
        prompt: str = SystemPromptBuilder.invoke(project_context_files=files)

        assert "workspace rules" in prompt
        assert '<project_instructions path="/abs/workspace/AGENTS.md">' in prompt

    # --- branch 9: cwd rendered when supplied, omitted when absent ---
    def test_renders_cwd_line_when_supplied(self) -> None:
        """A supplied cwd ends the prompt with the working-directory line."""
        prompt: str = SystemPromptBuilder.invoke(cwd="/home/user/project")
        assert "Current working directory: /home/user/project" in prompt

    def test_omits_cwd_line_when_absent(self) -> None:
        """No cwd -> the working-directory line is omitted entirely."""
        prompt: str = SystemPromptBuilder.invoke()
        assert "Current working directory:" not in prompt

    # --- branch 10: Windows-style separators normalized ---
    def test_normalizes_windows_separators_in_cwd_line(self) -> None:
        r"""Backslash separators are normalized to forward slashes in the cwd line."""
        prompt: str = SystemPromptBuilder.invoke(cwd=r"C:\repo\thing")
        assert "Current working directory: C:/repo/thing" in prompt
        assert r"C:\repo\thing" not in prompt

    # --- branch 11: current date renders as ISO YYYY-MM-DD ---
    def test_renders_current_date_in_iso_format(self) -> None:
        """The prompt grounds the model with an ISO 'Current date:' line.

        Uses a regex rather than comparing to date.today() to avoid a
        midnight-rollover flake when the test computes 'today' a moment after
        the builder did.
        """
        prompt: str = SystemPromptBuilder.invoke()
        assert re.search(r"Current date: \d{4}-\d{2}-\d{2}", prompt)

    def test_workspace_folders_block_omitted_when_absent(self) -> None:
        """No workspace folders means no workspace-folders block."""
        prompt: str = SystemPromptBuilder.invoke(cwd="/tmp/project")
        assert "Current workspace folders:" not in prompt

    def test_workspace_folders_block_renders_named_and_unnamed_entries(self, tmp_path) -> None:
        """Named folders render ``name (path)``; unnamed folders render path only."""
        alpha_path = (tmp_path / "alpha").resolve()
        beta_path = (tmp_path / "beta").resolve()
        folders: list[WorkspaceFolderDAO] = [
            WorkspaceFolderDAO(path=alpha_path, display_name="Alpha"),
            WorkspaceFolderDAO(path=beta_path, display_name=None),
        ]

        prompt: str = SystemPromptBuilder.invoke(
            cwd="/tmp/project",
            workspace_folders=folders,
        )

        assert "Current workspace folders:" in prompt
        assert f"  - Alpha ({alpha_path})" in prompt
        assert f"  - {beta_path}" in prompt
        assert f"  - None ({beta_path})" not in prompt


class TestSystemPromptBuilderXmlSkills:
    """Covers the XML skills block injected via the new ``skills`` parameter."""

    def _make_skills(self) -> list[SkillEntryDAO]:
        """Return a small fixture list of SkillEntryDAO objects."""
        return [
            SkillEntryDAO(
                name="build-routers",
                description="Adding or modifying FastAPI endpoints.",
                file_path="/abs/skills/coding/build-routers/SKILL.md",
            ),
            SkillEntryDAO(
                name="sync-main",
                description="Refresh local main from remote safely.",
                file_path="/abs/skills/git-ops/sync-main/SKILL.md",
            ),
        ]

    # --- XML present when skills loaded ---
    def test_available_skills_xml_block_present_when_skills_supplied(self) -> None:
        """When skills are provided the prompt contains the XML manifest header."""
        skills: list[SkillEntryDAO] = self._make_skills()
        prompt: str = SystemPromptBuilder.invoke(skills=skills)
        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt

    def test_each_skill_renders_name_description_location(self) -> None:
        """Every skill entry in the XML block has a <name>, <description>, and <location>."""
        skills: list[SkillEntryDAO] = self._make_skills()
        prompt: str = SystemPromptBuilder.invoke(skills=skills)
        for skill in skills:
            assert f"<name>{skill.name}</name>" in prompt
            assert f"<description>{skill.description}</description>" in prompt
            assert f"<location>{skill.file_path}</location>" in prompt

    def test_xml_replaces_skills_block_template_wording(self) -> None:
        """When skills are loaded the old INDEX.md pointer text is absent."""
        skills: list[SkillEntryDAO] = self._make_skills()
        prompt: str = SystemPromptBuilder.invoke(skills=skills)
        assert "## Skills" not in prompt
        assert "skills/INDEX.md" not in prompt

    def test_xml_preamble_lines_present(self) -> None:
        """The three instructional preamble lines appear before <available_skills>."""
        skills: list[SkillEntryDAO] = self._make_skills()
        prompt: str = SystemPromptBuilder.invoke(skills=skills)
        assert "The following skills provide specialized instructions for specific tasks." in prompt
        assert "Use the read tool to load a skill's file when the task matches its description." in prompt

    # --- fallback when skills list is empty ---
    def test_falls_back_to_index_pointer_when_skills_empty(self) -> None:
        """Empty skills list → the INDEX.md pointer block is rendered (no XML)."""
        prompt: str = SystemPromptBuilder.invoke(skills=[])
        assert "## Skills" in prompt
        assert "skills/INDEX.md" in prompt
        assert "<available_skills>" not in prompt

    def test_falls_back_to_index_pointer_when_skills_none(self) -> None:
        """skills=None → the INDEX.md pointer block is rendered (no XML)."""
        prompt: str = SystemPromptBuilder.invoke(skills=None)
        assert "## Skills" in prompt
        assert "skills/INDEX.md" in prompt
        assert "<available_skills>" not in prompt

    # --- XML escaping ---
    def test_xml_special_characters_are_escaped(self) -> None:
        """Names and descriptions with XML special characters are properly escaped."""
        skills: list[SkillEntryDAO] = [
            SkillEntryDAO(
                name="a&b<c>d",
                description='Use "quotes" & <tags>.',
                file_path="/abs/path/SKILL.md",
            ),
        ]
        prompt: str = SystemPromptBuilder.invoke(skills=skills)
        # raw special chars must not appear in the XML block
        assert "<name>a&b<c>d</name>" not in prompt
        # escaped forms must appear
        assert "&amp;" in prompt
        assert "&lt;" in prompt
        assert "&gt;" in prompt
        assert "&quot;" in prompt


class TestSystemPromptBuilderOrchestratorDefault:
    """Builder behaviour when ``DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT`` is the custom prompt."""

    def test_orchestrator_default_prompt_replaces_standard_role_line(self) -> None:
        """The orchestrator body replaces the standard solo-agent role sentence."""
        from src.agents.slo_agent.orchestrator.spawn_tool import DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        result: str = SystemPromptBuilder.invoke(
            custom_prompt=DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
        )
        assert "expert coding assistant operating inside slo" not in result
        assert "orchestrator" in result

    def test_orchestrator_default_prompt_retains_cwd_grounding(self) -> None:
        """CWD grounding block is still appended when using the orchestrator prompt."""
        from src.agents.slo_agent.orchestrator.spawn_tool import DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        result: str = SystemPromptBuilder.invoke(
            custom_prompt=DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
            cwd="/tmp/project",
        )
        assert "Current working directory: /tmp/project" in result

    def test_orchestrator_default_prompt_retains_date_grounding(self) -> None:
        """Date grounding line is still present when using the orchestrator prompt."""
        from src.agents.slo_agent.orchestrator.spawn_tool import DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        result: str = SystemPromptBuilder.invoke(
            custom_prompt=DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
        )
        assert "Current date:" in result
