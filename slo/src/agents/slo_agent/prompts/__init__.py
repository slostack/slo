"""Runtime system-prompt builder for slo.

Builds the final system prompt block by block so the prompt can reflect
runtime state such as active tools, discovered project guidance files,
and the current working directory.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional, Sequence

from langchain_core.tools import BaseTool

from config.cfg import SKILLS_DIR
from config.logger import log_info
from src.agents.slo_agent.project_context.dao import ContextFileEntryDAO
from src.agents.slo_agent.skills.dao import SkillEntryDAO
from src.agents.slo_agent.workspace.dao import WorkspaceFolderDAO
from src.agents.slo_agent.prompts.system_prompt import (
    ALWAYS_GUIDELINES,
    CUSTOM_TOOLS_NOTE,
    GUIDELINE_BASH_ONLY,
    GUIDELINE_PREFER_NATIVE_EXPLORERS,
    GUIDELINE_WRITE_CONTENT_INLINE,
    GUIDELINES_HEADER,
    KB_BLOCK,
    PROJECT_CONTEXT_CLOSE,
    PROJECT_CONTEXT_OPEN,
    PROJECT_INSTRUCTIONS_TEMPLATE,
    ROLE_LINE,
    SKILLS_BLOCK_TEMPLATE,
    WORKSPACE_FOLDERS_HEADER,
    WORKSPACE_FOLDER_LINE_PATH_ONLY,
    WORKSPACE_FOLDER_LINE_WITH_NAME,
)
from src.agents.tools.prompt_snippets import TOOL_PROMPT_SNIPPETS

__all__ = ["SYSTEM_PROMPT", "SystemPromptBuilder"]

from typing import Any as _Any


def __getattr__(name: str) -> _Any:
    if name == "SYSTEM_PROMPT":
        return SystemPromptBuilder.invoke()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class SystemPromptBuilder:
    """Assemble the runtime system prompt for a slo agent session.

    The builder keeps one public entry point, ``invoke()``, and pushes
    each section of the prompt into a dedicated helper method. This
    keeps the orchestration readable and makes each block easy to test
    in isolation.
    """

    @classmethod
    def invoke(
        cls,
        *,
        tools: Optional[Sequence[BaseTool]] = None,
        cwd: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        append_system_prompt: Optional[str] = None,
        project_context_files: Optional[list[ContextFileEntryDAO]] = None,
        skills: Optional[list[SkillEntryDAO]] = None,
        workspace_folders: Optional[list[WorkspaceFolderDAO]] = None,
    ) -> str:
        """Build the final system prompt for the current session.

        Args:
            tools (Optional[Sequence[BaseTool]], optional): Active tools
                bound to the agent. Defaults to None.
            cwd (Optional[str], optional): Working directory to surface
                at the end of the prompt. Defaults to None.
            custom_prompt (Optional[str], optional): Full prompt body
                that replaces the standard role/tools/guidelines body.
                Defaults to None.
            append_system_prompt (Optional[str], optional): Extra text
                appended after the default or custom prompt body.
                Defaults to None.
            project_context_files (Optional[list[ContextFileEntryDAO]], optional):
                Discovered project guidance files. Defaults to None.
            skills (Optional[list[SkillEntryDAO]], optional): Pre-loaded
                skill entries from ``SkillsLoader``. When non-empty the
                skills section renders as a structured ``<available_skills>``
                XML block; when empty or None it falls back to the
                INDEX.md pointer prose. Defaults to None.

        Returns:
            str: The fully assembled system prompt.
        """
        resolved_tools: Sequence[BaseTool] = tools or ()
        resolved_project_context_files: list[ContextFileEntryDAO] = list(project_context_files or [])
        resolved_cwd: Optional[str] = cls._resolve_cwd(cwd=cwd)
        resolved_skills: list[SkillEntryDAO] = list(skills or [])
        resolved_workspace_folders: list[WorkspaceFolderDAO] = list(workspace_folders or [])

        log_info(
            msg="SystemPromptBuilder.invoke",
            tools_count=len(resolved_tools),
            has_custom_prompt=custom_prompt is not None,
            has_append_prompt=bool(append_system_prompt and append_system_prompt.strip()),
            has_project_context=bool(resolved_project_context_files),
            skills_count=len(resolved_skills),
            workspace_folders_count=len(resolved_workspace_folders),
        )

        if custom_prompt is not None:
            return cls._assemble_custom_prompt(
                custom_prompt=custom_prompt,
                append_system_prompt=append_system_prompt,
                project_context_files=resolved_project_context_files,
                cwd=resolved_cwd,
                workspace_folders=resolved_workspace_folders,
            )

        sections: list[str] = [
            cls._build_role_line(),
            cls._build_tools_block(tools=resolved_tools),
            cls._build_custom_tools_note(),
            cls._build_guidelines_block(tools=resolved_tools),
            cls._build_skills_block(skills=resolved_skills),
            cls._build_knowledge_base_block(),
            cls._build_append_block(
                append_system_prompt=append_system_prompt,
            ),
            cls._build_project_context_block(
                project_context_files=resolved_project_context_files,
            ),
            cls._build_date_line(),
            cls._build_cwd_line(cwd=resolved_cwd),
            cls._build_workspace_folders_block(workspace_folders=resolved_workspace_folders),
        ]
        return "\n\n".join(section for section in sections if section)

    @classmethod
    def _resolve_cwd(cls, *, cwd: Optional[str]) -> Optional[str]:
        """Normalize the working directory before later prompt blocks use it.

        ``invoke()`` calls this near the start of prompt assembly so the
        downstream date/cwd branch and custom-prompt branch both receive
        the same normalized value. The helper does not touch the
        filesystem; it only prepares the string that later appears in
        the trailing ``Current working directory:`` line.

        Args:
            cwd (Optional[str]): Raw working directory path supplied by
                ``SloAgent`` during agent construction.

        Returns:
            Optional[str]: A normalized path with forward slashes, or
                None when cwd should be omitted from the prompt.
        """
        if cwd is None:
            return None
        return cwd.replace("\\", "/")

    @classmethod
    def _build_role_line(cls) -> str:
        """Return the prompt's role opener.

        Returns:
            str: The role/identity line.
        """
        return ROLE_LINE

    @classmethod
    def _build_tools_block(cls, *, tools: Sequence[BaseTool]) -> str:
        """Render the ``Available tools:`` block for the current session.

        ``invoke()`` calls this while assembling the default prompt body,
        after the role line and before the guidelines block. The helper
        walks the active tool objects supplied by ``SloAgent``, looks up
        each tool's ``.name`` in ``TOOL_PROMPT_SNIPPETS``, and emits only
        the tools that have a registered prompt-facing sentence.

        Args:
            tools (Sequence[BaseTool]): Active tools for this run.

        Returns:
            str: The rendered tools section. If no tools have registered
                snippets, the section renders ``(none)``.
        """
        lines: list[str] = []
        tool: BaseTool
        for tool in tools:
            snippet: Optional[str] = TOOL_PROMPT_SNIPPETS.get(tool.name)
            if snippet is None:
                continue
            lines.append(f"- {tool.name}: {snippet}")

        if not lines:
            return "Available tools:\n(none)"
        return "Available tools:\n" + "\n".join(lines)

    @classmethod
    def _build_custom_tools_note(cls) -> str:
        """Return the note about project-specific tools.

        Returns:
            str: The custom-tools note.
        """
        return CUSTOM_TOOLS_NOTE

    @classmethod
    def _build_guidelines_block(cls, *, tools: Sequence[BaseTool]) -> str:
        """Render the Guidelines block for the current tool bundle.

        ``invoke()`` calls this immediately after the tools section so
        the prompt can explain how the model should use the tools it was
        just shown. In practice this method is where the builder decides
        whether the prompt should prefer ``bash`` for exploration or
        prefer the dedicated ``grep`` / ``find`` / ``ls`` tools.

        Args:
            tools (Sequence[BaseTool]): Active tools for this run.

        Returns:
            str: The fully rendered guidelines section.
        """
        tool_names: set[str] = {tool.name for tool in tools}
        guideline_lines: list[str] = []

        if "bash" in tool_names and not ({"grep", "find", "ls"} & tool_names):
            guideline_lines.append(GUIDELINE_BASH_ONLY)
        elif "bash" in tool_names:
            guideline_lines.append(GUIDELINE_PREFER_NATIVE_EXPLORERS)

        if "write" in tool_names:
            guideline_lines.append(GUIDELINE_WRITE_CONTENT_INLINE)

        guideline_lines.extend(ALWAYS_GUIDELINES)
        bullet_lines: list[str] = [f"- {line}" for line in guideline_lines]
        return GUIDELINES_HEADER + "\n" + "\n".join(bullet_lines)

    @classmethod
    def _build_skills_block(cls, *, skills: Optional[list[SkillEntryDAO]] = None) -> str:
        """Return the skills section: XML manifest when skills are loaded, else INDEX.md pointer.

        Args:
            skills (Optional[list[SkillEntryDAO]]): Pre-loaded skill entries.
                When non-empty the method returns the structured XML block.
                When empty or None it falls back to the INDEX.md pointer prose
                so sessions without a resolvable skills dir still get guidance.

        Returns:
            str: The rendered skills section.
        """
        if skills:
            return cls._format_skills_as_xml(skills=skills)
        skills_index_path: str = os.path.join(SKILLS_DIR, "INDEX.md")
        return SKILLS_BLOCK_TEMPLATE.format(
            skills_index_path=skills_index_path,
        ).strip()

    @classmethod
    def _build_knowledge_base_block(cls) -> str:
        """Return the knowledge base guidance block.

        Returns:
            str: The rendered knowledge base block.
        """
        return KB_BLOCK.strip()

    @classmethod
    def _format_skills_as_xml(cls, *, skills: list[SkillEntryDAO]) -> str:
        """Format skill entries as an AgentSkills.io XML block.

        Produces the structured ``<available_skills>`` format that the model
        can match against without a prior read-tool call to ``INDEX.md``.

        Args:
            skills (list[SkillEntryDAO]): Parsed invocable skill entries.

        Returns:
            str: XML block, or empty string when skills list is empty.
        """
        if not skills:
            return ""
        lines: list[str] = [
            "The following skills provide specialized instructions for specific tasks.",
            "Use the read tool to load a skill's file when the task matches its description.",
            "When a skill file references a relative path, resolve it against the skill directory "
            "(parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.",
            "",
            "<available_skills>",
        ]
        skill: SkillEntryDAO
        for skill in skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{cls._escape_xml(text=skill.name)}</name>")
            lines.append(f"    <description>{cls._escape_xml(text=skill.description)}</description>")
            lines.append(f"    <location>{cls._escape_xml(text=skill.file_path)}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    @staticmethod
    def _escape_xml(*, text: str) -> str:
        """Escape the five XML special characters.

        Args:
            text (str): Raw text to escape.

        Returns:
            str: XML-safe text.
        """
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    @classmethod
    def _build_append_block(
        cls,
        *,
        append_system_prompt: Optional[str],
    ) -> str:
        """Render the optional caller-supplied append block.

        ``invoke()`` and ``_assemble_custom_prompt()`` both call this
        helper when the session may include extra instructions layered on
        top of the standard prompt body. This is the extension point used
        when the caller wants to add free-form guidance without replacing
        the entire prompt.

        Args:
            append_system_prompt (Optional[str]): Caller-supplied text
                to append after the default or custom body.

        Returns:
            str: The trimmed appended text, or an empty string when no
                append text should be emitted.
        """
        if not append_system_prompt:
            return ""

        stripped_append_system_prompt: str = append_system_prompt.strip()
        if not stripped_append_system_prompt:
            return ""
        return stripped_append_system_prompt

    @classmethod
    def _build_project_context_block(
        cls,
        *,
        project_context_files: list[ContextFileEntryDAO],
    ) -> str:
        """Render the tagged project-context wrapper block.

        ``invoke()`` calls this late in prompt assembly, after the base
        slo instructions have already been rendered, so host-repository
        guidance appears as an additive context layer. The helper is used
        whenever ``SloAgent`` has already discovered one or more
        ``SLO.md`` / ``AGENTS.md`` / ``CLAUDE.md`` files and needs to
        serialize them into the final prompt in a machine-readable way.
        Global-tier entries are rendered before project-tier entries.

        Args:
            project_context_files (list[ContextFileEntryDAO]): Discovered
                project instruction files with tier annotations.

        Returns:
            str: The rendered project context block, or an empty string
                when no files were discovered.
        """
        if not project_context_files:
            return ""

        rendered_entries: list[str] = []
        entry: ContextFileEntryDAO
        for entry in project_context_files:
            rendered_entries.append(
                PROJECT_INSTRUCTIONS_TEMPLATE.format(
                    path=entry.path,
                    content=entry.content,
                )
            )

        return PROJECT_CONTEXT_OPEN + "\n\n".join(rendered_entries) + "\n\n" + PROJECT_CONTEXT_CLOSE

    @classmethod
    def _build_date_line(cls) -> str:
        """Return the current date line.

        Returns:
            str: The current date in ISO format.
        """
        return f"Current date: {date.today().isoformat()}"

    @classmethod
    def _build_workspace_folders_block(
        cls,
        *,
        workspace_folders: list[WorkspaceFolderDAO],
    ) -> str:
        """Render the workspace-folders block when folders are present.

        Args:
            workspace_folders: Resolved workspace folders in declaration order.

        Returns:
            str: The rendered block, or an empty string when no folders exist.
        """
        if not workspace_folders:
            return ""

        lines: list[str] = [WORKSPACE_FOLDERS_HEADER]
        folder: WorkspaceFolderDAO
        for folder in workspace_folders:
            if folder.display_name:
                lines.append(
                    WORKSPACE_FOLDER_LINE_WITH_NAME.format(
                        name=folder.display_name,
                        path=str(folder.path),
                    )
                )
                continue
            lines.append(WORKSPACE_FOLDER_LINE_PATH_ONLY.format(path=str(folder.path)))
        return "\n".join(lines)

    @classmethod
    def _build_cwd_line(cls, *, cwd: Optional[str]) -> str:
        """Render the trailing working-directory line for the prompt.

        ``invoke()`` calls this as one of the final prompt blocks so the
        model ends the system prompt with the concrete directory it is
        operating inside. The helper is also reused by the custom-prompt
        branch so both prompt paths end with the same cwd grounding.

        Args:
            cwd (Optional[str]): Normalized working directory.

        Returns:
            str: The cwd line, or an empty string when cwd is absent.
        """
        if cwd is None:
            return ""
        return f"Current working directory: {cwd}"

    @classmethod
    def _assemble_custom_prompt(
        cls,
        *,
        custom_prompt: str,
        append_system_prompt: Optional[str],
        project_context_files: list[ContextFileEntryDAO],
        cwd: Optional[str],
        workspace_folders: list[WorkspaceFolderDAO],
    ) -> str:
        """Build the alternate prompt path used for full prompt overrides.

        ``invoke()`` routes here when the caller supplies
        ``custom_prompt``. The method does not rebuild the default
        role/tools/guidelines body; instead it starts from the custom
        body and then layers on the same runtime grounding blocks that a
        normal session would still need: appended text, project context,
        current date, and cwd.

        Args:
            custom_prompt (str): Full replacement for the default body.
            append_system_prompt (Optional[str]): Optional prompt text
                appended after the custom prompt.
            project_context_files (list[ContextFileEntryDAO]): Discovered
                project guidance files with tier annotations.
            cwd (Optional[str]): Normalized working directory.

        Returns:
            str: The final prompt when a custom prompt was supplied.
        """
        sections: list[str] = [
            custom_prompt.strip(),
            cls._build_append_block(
                append_system_prompt=append_system_prompt,
            ),
            cls._build_project_context_block(
                project_context_files=project_context_files,
            ),
            cls._build_date_line(),
            cls._build_cwd_line(cwd=cwd),
            cls._build_workspace_folders_block(workspace_folders=workspace_folders),
        ]
        return "\n\n".join(section for section in sections if section)


# SYSTEM_PROMPT is resolved lazily via module __getattr__ above so that
# SystemPromptBuilder.invoke() is never called at import time.
