"""Tool bundle factories — pre-assembled lists for common cases (25.a.6).

The three pi-parity bundles (``create_coding_tools``,
``create_read_only_tools``, ``create_all_tools``) mirror pi's
``createCodingTools`` / ``createReadOnlyTools`` / ``createAllTools`` at
``pi/packages/coding-agent/src/core/tools/index.ts``.

``create_local_tools`` is the slo-specific set of ten built-in tools
(the kitchen-sink set plus ``read_pdf``, ``now`` and ``show_git_diff``). It
never touches connector credentials, so routes that cannot use connectors
(the Claude bridge) take it directly.

``create_extended_tools`` is the local set plus any configured connector
tools, for workflows that also need to reach Confluence and Jira.

``create_connector_tools`` returns only the connector tools whose provider
credentials resolve at bundle-build time.  This keeps the prompt truthful:
dead tools that cannot be authenticated are never shown.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from src.agents.tools.bash import bash_tool
from src.agents.tools.edit import edit_tool
from src.agents.tools.find import find_tool
from src.agents.tools.grep import grep_tool
from src.agents.tools.ls import ls_tool
from src.agents.tools.now import now_tool
from src.agents.tools.read import read_tool
from src.agents.tools.read_pdf import read_pdf_tool
from src.agents.tools.show_git_diff import show_git_diff_tool
from src.agents.tools.write import write_tool


def create_coding_tools() -> list[BaseTool]:
    """Pi's default coding bundle: read, bash, edit, write.

    Mirrors ``createCodingTools`` at
    pi/packages/coding-agent/src/core/tools/index.ts:168-175.
    """
    return [read_tool, bash_tool, edit_tool, write_tool]


def create_read_only_tools() -> list[BaseTool]:
    """Browse-only bundle: read, grep, find, ls.

    Mirrors ``createReadOnlyTools`` at
    pi/packages/coding-agent/src/core/tools/index.ts:177-184.
    """
    return [read_tool, grep_tool, find_tool, ls_tool]


def create_all_tools() -> list[BaseTool]:
    """All seven pi-parity coding tools.

    Mirrors ``createAllTools`` at
    pi/packages/coding-agent/src/core/tools/index.ts:186-196.
    """
    return [
        read_tool,
        write_tool,
        edit_tool,
        bash_tool,
        grep_tool,
        find_tool,
        ls_tool,
    ]


def create_connector_tools() -> list[BaseTool]:
    """Return connector tools whose provider credentials are currently configured.

    Each provider's tools are only included when
    ``ConnectorCredentialResolver.is_configured`` returns ``True`` for that
    provider.  This avoids exposing tools in the system prompt that would
    immediately fail with a missing-credential error.

    Today only Atlassian (Confluence + Jira) tools are included.  GitHub and
    GitLab connector tools will be added in a later slice.

    Returns:
        list[BaseTool]: Active connector tools for this session.
    """
    from src.agents.tools.create_jira_issue import create_jira_issue_tool  # noqa: PLC0415
    from src.agents.tools.get_confluence_page import get_confluence_page_tool  # noqa: PLC0415
    from src.agents.tools.get_jira_issue import get_jira_issue_tool  # noqa: PLC0415
    from src.agents.tools.search_confluence_using_cql import (  # noqa: PLC0415
        search_confluence_using_cql_tool,
    )
    from src.agents.tools.search_jira_using_jql import search_jira_using_jql_tool  # noqa: PLC0415
    from src.integrations.connectors.credentials import (  # noqa: PLC0415
        ConnectorCredentialResolver,
        ConnectorProviderName,
    )

    tools: list[BaseTool] = []

    if ConnectorCredentialResolver.is_configured(provider=ConnectorProviderName.ATLASSIAN):
        tools.extend(
            [
                search_confluence_using_cql_tool,
                get_confluence_page_tool,
                search_jira_using_jql_tool,
                get_jira_issue_tool,
                create_jira_issue_tool,
            ]
        )

    return tools


def create_local_tools() -> list[BaseTool]:
    """The ten local tools: read, write, edit, bash, grep, find, ls, read_pdf, now, show_git_diff.

    Never touches connector credentials.
    """
    return [
        *create_all_tools(),
        read_pdf_tool,
        now_tool,
        show_git_diff_tool,
    ]


def create_extended_tools() -> list[BaseTool]:
    """Local tools plus configured connector tools (behaviour and order unchanged).

    Use this bundle for sessions that need document awareness, timestamps,
    HEAD-versus-worktree diffs, and optional remote planning-system access.
    """
    return [*create_local_tools(), *create_connector_tools()]
