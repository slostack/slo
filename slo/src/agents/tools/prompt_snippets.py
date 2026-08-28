"""Prompt-facing one-line descriptions for built-in and connector tools (25.a.6)."""
from __future__ import annotations

from src.agents.tools.bash import BASH_PROMPT_SNIPPET
from src.agents.tools.create_jira_issue import CREATE_JIRA_ISSUE_PROMPT_SNIPPET
from src.agents.tools.edit import EDIT_PROMPT_SNIPPET
from src.agents.tools.find import FIND_PROMPT_SNIPPET
from src.agents.tools.get_confluence_page import GET_CONFLUENCE_PAGE_PROMPT_SNIPPET
from src.agents.tools.get_jira_issue import GET_JIRA_ISSUE_PROMPT_SNIPPET
from src.agents.tools.grep import GREP_PROMPT_SNIPPET
from src.agents.tools.ls import LS_PROMPT_SNIPPET
from src.agents.tools.now import NOW_PROMPT_SNIPPET
from src.agents.tools.read import READ_PROMPT_SNIPPET
from src.agents.tools.read_pdf import READ_PDF_PROMPT_SNIPPET
from src.agents.tools.search_confluence_using_cql import SEARCH_CONFLUENCE_USING_CQL_PROMPT_SNIPPET
from src.agents.tools.search_jira_using_jql import SEARCH_JIRA_USING_JQL_PROMPT_SNIPPET
from src.agents.tools.write import WRITE_PROMPT_SNIPPET

__all__ = ["TOOL_PROMPT_SNIPPETS"]

TOOL_PROMPT_SNIPPETS: dict[str, str] = {
    # Built-in local tools
    "read": READ_PROMPT_SNIPPET,
    "write": WRITE_PROMPT_SNIPPET,
    "edit": EDIT_PROMPT_SNIPPET,
    "bash": BASH_PROMPT_SNIPPET,
    "grep": GREP_PROMPT_SNIPPET,
    "find": FIND_PROMPT_SNIPPET,
    "ls": LS_PROMPT_SNIPPET,
    "now": NOW_PROMPT_SNIPPET,
    "read_pdf": READ_PDF_PROMPT_SNIPPET,
    # Confluence connector tools (25.a.2)
    "search_confluence_using_cql": SEARCH_CONFLUENCE_USING_CQL_PROMPT_SNIPPET,
    "get_confluence_page": GET_CONFLUENCE_PAGE_PROMPT_SNIPPET,
    # Jira connector tools (25.a.3)
    "search_jira_using_jql": SEARCH_JIRA_USING_JQL_PROMPT_SNIPPET,
    "get_jira_issue": GET_JIRA_ISSUE_PROMPT_SNIPPET,
    "create_jira_issue": CREATE_JIRA_ISSUE_PROMPT_SNIPPET,
}
