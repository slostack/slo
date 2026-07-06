"""Session management submodule for SloAgentSession.

Imports are kept lazy to avoid circular-import issues: agent.py imports
from session_usage_dao (which re-exports from sessions/usage.py), and
sessions/service.py imports from agent.py. Eagerly importing SloAgentSession
here would form a cycle at package init time.

Import directly from the sub-modules when you need specific names:
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.usage import TokenUsageTotalsDAO
"""
