import os
from pathlib import Path
from typing import Optional

from config.timeout_resolver import positive_float_env

__all__ = ["cfg", "__cfg__", "is_dev", "is_test", "is_staging", "USER_SKILLS_DIR", "USER_WORKFLOWS_DIR"]

env = os.environ.get("SLO_ENV", "development")


def is_dev() -> bool:
    return env == "development"


def is_test() -> bool:
    return env == "test"


def is_staging() -> bool:
    return env == "staging"


APP_NAME = os.environ.get("SLO_APP_NAME", "slo")
DB_URL = os.environ.get("SLO_DB_URL", None)
DB_URL_ASYNC = os.environ.get("SLO_DB_URL_ASYNC", None)
APP_DIR = os.environ.get("SLO_APP_DIR", None)
REDIS_URL = os.environ.get("SLO_REDIS_URL", None)
BASE_URL = os.environ.get("SLO_BASE_URL", "http://localhost:7700/slo")
DOMAIN = os.environ.get("SLO_DOMAIN", "localhost:7700")
LOG_FORMAT = os.environ.get("SLO_LOG_FORMAT", "json")

# Provider keys
ANTHROPIC_API_KEY = os.environ.get("SLO_ANTHROPIC_API_KEY", None)
OPENAI_API_KEY = os.environ.get("SLO_OPENAI_API_KEY", None)
KIMI_FOR_CODING_API_KEY = os.environ.get("SLO_KIMI_FOR_CODING_API_KEY", None)
DEFAULT_MODEL_NAME = os.environ.get("SLO_DEFAULT_MODEL_NAME", "gpt-5.4")

# Network ports
A2A_PORT = int(os.environ.get("SLO_A2A_PORT", "9900"))
A2A_PUBLIC_URL = os.environ.get("SLO_A2A_PUBLIC_URL", "http://localhost:9900")
WEB_PORT = int(os.environ.get("SLO_WEB_PORT", "7700"))

# A2A peer tool timeouts
A2A_FETCH_TIMEOUT_SECONDS: float = positive_float_env(
    primary_name="SLO_A2A_FETCH_TIMEOUT_SECONDS",
    default=10.0,
)
A2A_INVOKE_TIMEOUT_SECONDS: float = positive_float_env(
    primary_name="SLO_A2A_INVOKE_TIMEOUT_SECONDS",
    default=300.0,
)

# Atlassian / Jira / Confluence integration
ATLASSIAN_API_TOKEN: Optional[str] = os.environ.get("SLO_ATLASSIAN_API_TOKEN")
ATLASSIAN_EMAIL: Optional[str] = os.environ.get("SLO_ATLASSIAN_EMAIL")
ATLASSIAN_SITE_URL: Optional[str] = os.environ.get("SLO_ATLASSIAN_SITE_URL")
_ATLASSIAN_TIMEOUT_RAW: Optional[str] = os.environ.get("SLO_ATLASSIAN_TIMEOUT_SECONDS")
ATLASSIAN_TIMEOUT_SECONDS: Optional[int] = int(_ATLASSIAN_TIMEOUT_RAW) if _ATLASSIAN_TIMEOUT_RAW else None

# Integration connector store root and env-credential preference
CONNECTORS_DIR: Optional[str] = os.environ.get("SLO_CONNECTORS_DIR")
CONNECTOR_PREFER_ENV: bool = os.environ.get("SLO_CONNECTOR_PREFER_ENV", "").strip() == "1"

# Debug / development tooling (debugpy remote-attach)
DEBUGPY: Optional[str] = os.environ.get("SLO_DEBUGPY")
DEBUGPY_PORT: int = int(os.environ.get("SLO_DEBUGPY_PORT", "5678"))

# Deploy / update credentials (consumed by ``slo update``). The public install.sh
# names are SLO_USERNAME / SLO_TOKEN; the internal aliases are preferred when both
# are present.
DEPLOY_TOKEN: Optional[str] = (
    os.environ.get("SLO_DEPLOY_TOKEN") or os.environ.get("SLO_TOKEN")
)
DEPLOY_TOKEN_USERNAME: Optional[str] = (
    os.environ.get("SLO_DEPLOY_TOKEN_USERNAME") or os.environ.get("SLO_USERNAME")
)

# GitHub integration
GITHUB_API_BASE_URL: Optional[str] = os.environ.get("SLO_GITHUB_API_BASE_URL")
_GITHUB_TIMEOUT_RAW: Optional[str] = os.environ.get("SLO_GITHUB_TIMEOUT_SECONDS")
GITHUB_TIMEOUT_SECONDS: Optional[int] = int(_GITHUB_TIMEOUT_RAW) if _GITHUB_TIMEOUT_RAW else None
GITHUB_TOKEN: Optional[str] = (
    os.environ.get("GITHUB_TOKEN")
    or os.environ.get("GH_TOKEN")
    or os.environ.get("SLO_GITHUB_TOKEN")
)

# GitLab integration
GITLAB_API_BASE_URL: Optional[str] = os.environ.get("SLO_GITLAB_API_BASE_URL")
_GITLAB_TIMEOUT_RAW: Optional[str] = os.environ.get("SLO_GITLAB_TIMEOUT_SECONDS")
GITLAB_TIMEOUT_SECONDS: Optional[int] = int(_GITLAB_TIMEOUT_RAW) if _GITLAB_TIMEOUT_RAW else None
GITLAB_TOKEN: Optional[str] = (
    os.environ.get("GITLAB_TOKEN")
    or os.environ.get("GLAB_TOKEN")
    or os.environ.get("SLO_GITLAB_TOKEN")
)

# OAuth callback host (used by both Anthropic and OpenAI Codex provider flows)
OAUTH_CALLBACK_HOST: str = os.environ.get("SLO_OAUTH_CALLBACK_HOST", "127.0.0.1")

# User preferences file override
PREFERENCES_FILE: Optional[str] = os.environ.get("SLO_PREFERENCES_FILE")

# Python / pyenv version (used by ``slo update`` installer)
PYENV_ROOT: Optional[str] = os.environ.get("PYENV_ROOT")
PYTHON_VERSION: Optional[str] = os.environ.get("SLO_PYTHON_VERSION")

# Schedules store root override
SCHEDULES_DIR: Optional[str] = os.environ.get("SLO_SCHEDULES_DIR")

# Session identity (headless runner pin; empty string means "assign a fresh id")
SESSION_ID: str = os.environ.get("SLO_SESSION_ID", "").strip()

# Sub-agent pool concurrency caps
SUBAGENT_MAX_CONCURRENCY: int = int(os.environ.get("SLO_SUBAGENT_MAX_CONCURRENCY", "4"))
SUBAGENT_MAX_TASKS: int = int(os.environ.get("SLO_SUBAGENT_MAX_TASKS", "8"))

# Sub-agent / orchestrator timeout values
STREAM_INACTIVITY_TIMEOUT_SECONDS: float = positive_float_env(
    primary_name="SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS",
    default=2400.0,
)
SUBAGENT_TERMINATE_GRACE_SECONDS: float = positive_float_env(
    primary_name="SLO_SUBAGENT_TERMINATE_GRACE_SECONDS",
    default=5.0,
)
SUBAGENT_INACTIVITY_TIMEOUT_SECONDS: float = positive_float_env(
    primary_name="SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS",
    alias_name="SLO_SUBAGENT_INACTIVITY_TIMEOUT",
    default=1800.0,
)

# Visualizer polling cadence
VISUALIZER_REFRESH_SECONDS: float = positive_float_env(
    primary_name="SLO_VISUALIZER_REFRESH_SECONDS",
    default=2.0,
)

# Tool defaults
TOOL_BASE_DIR = os.environ.get("SLO_TOOL_BASE_DIR", os.getcwd())

# Authentication storage (02.b.1). ``SLO_HOME`` is the persistent root used by
# the installer; ``SLO_AUTH_FILE`` is where ``CredentialStore`` reads and writes.
SLO_HOME = Path(os.environ.get("SLO_HOME", str(Path.home() / ".slo")))
SLO_AUTH_FILE = Path(os.environ.get(
    "SLO_AUTH_FILE",
    str(SLO_HOME / "global" / "authentication.json"),
))

# OAuth flow timeout (02.b.3). Seconds the ``_CallbackServer`` will wait for
# the browser-side redirect before raising ``OAuthTimeoutError``.
SLO_OAUTH_TIMEOUT_SECONDS = int(os.environ.get("SLO_OAUTH_TIMEOUT_SECONDS", "60"))

# Skills + Knowledge Base (01.l + 01.n)
# SKILLS_DIR is the absolute path to the committed skills/ directory. The
# system prompt references the index at ``<SKILLS_DIR>/INDEX.md``; the agent
# reads it on demand via the ``read`` tool — there is no runtime injection.
def _resolve_skills_dir() -> str:
    """Pick the skills directory by precedence (sub-spec 01.n §5.4).

    Order:
        1. ``$SLO_SKILLS_DIR`` if set (explicit override; honoured for tests
           and one-off experiments).
        2. ``~/.slo/skills`` if it exists (the pipx install path from 01.n).
        3. The repo-local ``skills/`` directory next to this file (dev clones).

    Returns:
        Absolute path string. Never ``None`` — falls through to the repo-local
        path even if it does not exist, so misconfiguration surfaces as
        "FileNotFoundError when reading INDEX.md" rather than a silent None.
    """
    override = os.environ.get("SLO_SKILLS_DIR")
    if override:
        return os.path.abspath(override)

    installed = Path.home() / ".slo" / "skills"
    if installed.is_dir():
        return str(installed)

    repo_root = Path(__file__).resolve().parent.parent
    return str(repo_root / "skills")


SKILLS_DIR: str = _resolve_skills_dir()

# User-defined skills and workflows (spec 29).
# These directories are created on first write by the creation skills;
# their absence at session start is not an error.
USER_SKILLS_DIR: str = os.environ.get(
    "SLO_USER_SKILLS_DIR",
    str(SLO_HOME / "user_skills"),
)
USER_WORKFLOWS_DIR: str = os.environ.get(
    "SLO_USER_WORKFLOWS_DIR",
    str(SLO_HOME / "user_workflows"),
)

# SLO_KB_DIR is the local one-way mirror of the canonical knowledge base.
# Slo reads and writes only this path; the system prompt references the env
# variable name so the agent can resolve it via bash if needed.
SLO_KB_DIR = os.environ.get("SLO_KB_DIR", None)
# SLO_KB_SOURCE is the canonical KB path that ``make kb-snapshot`` mirrors from.
SLO_KB_SOURCE = os.environ.get("SLO_KB_SOURCE", None)

__cfg__: dict[str, str | None] = {
    "A2A_FETCH_TIMEOUT_SECONDS": str(A2A_FETCH_TIMEOUT_SECONDS),
    "A2A_INVOKE_TIMEOUT_SECONDS": str(A2A_INVOKE_TIMEOUT_SECONDS),
    "A2A_PORT": str(A2A_PORT),
    "A2A_PUBLIC_URL": A2A_PUBLIC_URL,
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "APP_DIR": APP_DIR,
    "APP_NAME": APP_NAME,
    "ATLASSIAN_API_TOKEN": ATLASSIAN_API_TOKEN,
    "ATLASSIAN_EMAIL": ATLASSIAN_EMAIL,
    "ATLASSIAN_SITE_URL": ATLASSIAN_SITE_URL,
    "ATLASSIAN_TIMEOUT_SECONDS": str(ATLASSIAN_TIMEOUT_SECONDS) if ATLASSIAN_TIMEOUT_SECONDS is not None else None,
    "BASE_URL": BASE_URL,
    "CONNECTORS_DIR": CONNECTORS_DIR,
    "CONNECTOR_PREFER_ENV": "1" if CONNECTOR_PREFER_ENV else "0",
    "DB_URL": DB_URL,
    "DB_URL_ASYNC": DB_URL_ASYNC,
    "DEBUGPY": DEBUGPY,
    "DEBUGPY_PORT": str(DEBUGPY_PORT),
    "DEFAULT_MODEL_NAME": DEFAULT_MODEL_NAME,
    "DEPLOY_TOKEN": DEPLOY_TOKEN,
    "DEPLOY_TOKEN_USERNAME": DEPLOY_TOKEN_USERNAME,
    "DOMAIN": DOMAIN,
    "ENV": env,
    "GITHUB_API_BASE_URL": GITHUB_API_BASE_URL,
    "GITHUB_TIMEOUT_SECONDS": str(GITHUB_TIMEOUT_SECONDS) if GITHUB_TIMEOUT_SECONDS is not None else None,
    # GITHUB_TOKEN is intentionally absent: resolved purely via os.environ so
    # monkeypatch.delenv("GITHUB_TOKEN") works correctly in tests.
    "GITLAB_API_BASE_URL": GITLAB_API_BASE_URL,
    "GITLAB_TIMEOUT_SECONDS": str(GITLAB_TIMEOUT_SECONDS) if GITLAB_TIMEOUT_SECONDS is not None else None,
    # GITLAB_TOKEN is intentionally absent: same reason as GITHUB_TOKEN above.
    "KIMI_FOR_CODING_API_KEY": KIMI_FOR_CODING_API_KEY,
    "LOG_FORMAT": LOG_FORMAT,
    "OAUTH_CALLBACK_HOST": OAUTH_CALLBACK_HOST,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "PREFERENCES_FILE": PREFERENCES_FILE,
    "PYENV_ROOT": PYENV_ROOT,
    "PYTHON_VERSION": PYTHON_VERSION,
    "REDIS_URL": REDIS_URL,
    "SCHEDULES_DIR": SCHEDULES_DIR,
    "SESSION_ID": SESSION_ID,
    "SKILLS_DIR": SKILLS_DIR,
    "SLO_AUTH_FILE": str(SLO_AUTH_FILE),
    "SLO_HOME": str(SLO_HOME),
    "SLO_KB_DIR": SLO_KB_DIR,
    "SLO_KB_SOURCE": SLO_KB_SOURCE,
    "SLO_OAUTH_TIMEOUT_SECONDS": str(SLO_OAUTH_TIMEOUT_SECONDS),
    "SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS": str(STREAM_INACTIVITY_TIMEOUT_SECONDS),
    "SUBAGENT_INACTIVITY_TIMEOUT_SECONDS": str(SUBAGENT_INACTIVITY_TIMEOUT_SECONDS),
    "SUBAGENT_MAX_CONCURRENCY": str(SUBAGENT_MAX_CONCURRENCY),
    "SUBAGENT_MAX_TASKS": str(SUBAGENT_MAX_TASKS),
    "SUBAGENT_TERMINATE_GRACE_SECONDS": str(SUBAGENT_TERMINATE_GRACE_SECONDS),
    "TOOL_BASE_DIR": TOOL_BASE_DIR,
    "USER_SKILLS_DIR": USER_SKILLS_DIR,
    "USER_WORKFLOWS_DIR": USER_WORKFLOWS_DIR,
    "VISUALIZER_REFRESH_SECONDS": str(VISUALIZER_REFRESH_SECONDS),
    "WEB_PORT": str(WEB_PORT),
}


def cfg(key: str) -> str | None:
    """Return the configured value for ``key``.

    Checks ``os.environ`` first so test-time ``monkeypatch.setenv`` /
    ``monkeypatch.delenv`` overrides are respected, then falls back to
    the pre-loaded ``__cfg__`` dict for short-name aliases (e.g.
    ``"DEFAULT_MODEL_NAME"`` → ``SLO_DEFAULT_MODEL_NAME``).

    Keys that are NOT in ``__cfg__`` (e.g. ``GITHUB_TOKEN``,
    ``GITLAB_TOKEN``) are resolved purely from ``os.environ`` so that
    ``monkeypatch.delenv`` removes them completely.
    """
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
    return __cfg__.get(key)
