"""Canonical managed-plugin identity and public-name derivation."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

__all__ = ["PluginIdentityDAO"]

_SUPPORTED_HOSTS: frozenset[str] = frozenset({"github.com", "gitlab.com"})
_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class PluginIdentityDAO(BaseModel):
    """The I/O-free namespace derived from one supported plugin source URL.

    WHAT: Owns every public name deriving from an installed plugin source.
    WHO: Used by the installer before copying files and by the loader before import.
    WHEN: Once for every managed plugin, before its code is ever executed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    plugin_id: str
    source_url: str
    module_name: str

    @classmethod
    def from_source_url(cls, *, source_url: str) -> "PluginIdentityDAO":
        """Derive one canonical identity from a GitHub or GitLab HTTPS URL.

        Args:
            source_url (str): Operator-supplied source URL.

        Returns:
            PluginIdentityDAO: Normalized source provenance and derived names.

        Raises:
            ValueError: If the URL is not a supported owner-repository HTTPS URL.
        """
        parsed = urlparse(source_url)
        host: str = parsed.hostname.lower() if parsed.hostname is not None else ""
        path_parts: list[str] = [part for part in parsed.path.strip("/").split("/") if part]
        if parsed.scheme != "https" or host not in _SUPPORTED_HOSTS or len(path_parts) != 2:
            raise ValueError("plugin source must be a supported GitHub or GitLab HTTPS owner-repository URL")
        owner: str = cls._normalize_component(component=path_parts[0])
        repository: str = cls._normalize_component(component=path_parts[1].removesuffix(".git"))
        plugin_id: str = f"{owner}-{repository}"
        return cls(
            namespace=plugin_id,
            plugin_id=plugin_id,
            source_url=f"https://{host}/{owner}/{repository}",
            module_name=f"slo_plugin_{plugin_id.replace('-', '_')}",
        )

    def tool_name(self, *, suffix: str) -> str:
        """Derive an LLM-visible name from a plugin-local tool suffix.

        Args:
            suffix (str): Local plugin tool token.

        Returns:
            str: Namespace-prefixed tool name.

        Raises:
            ValueError: If the suffix is not a safe plugin token.
        """
        return f"{self._snake_namespace()}__{self._validated_suffix(suffix=suffix)}"

    def command_token(self, *, suffix: str) -> str:
        """Derive a slash-command token from a plugin-local suffix.

        Args:
            suffix (str): Local plugin command token.

        Returns:
            str: Namespace-prefixed slash-command token.

        Raises:
            ValueError: If the suffix is not a safe plugin token.
        """
        return f"/{self.namespace}:{self._validated_suffix(suffix=suffix)}"

    def status_key(self, *, suffix: str) -> str:
        """Derive a footer-status key from a plugin-local suffix.

        Args:
            suffix (str): Local plugin status token.

        Returns:
            str: Namespace-prefixed status key.

        Raises:
            ValueError: If the suffix is not a safe plugin token.
        """
        return f"{self.namespace}:{self._validated_suffix(suffix=suffix)}"

    @classmethod
    def _normalize_component(cls, *, component: str) -> str:
        """Normalize and validate a source URL owner or repository component.

        Args:
            component (str): Source URL path component.

        Returns:
            str: Lowercase safe component.

        Raises:
            ValueError: If the component cannot be a stable plugin identity.
        """
        normalized: str = component.lower()
        if not _TOKEN_PATTERN.fullmatch(normalized):
            raise ValueError("plugin source must be a supported GitHub or GitLab HTTPS owner-repository URL")
        return normalized

    def _validated_suffix(self, *, suffix: str) -> str:
        """Validate one plugin-local suffix before deriving a public name.

        Args:
            suffix (str): Suffix supplied by the plugin manifest or registration.

        Returns:
            str: Validated lowercase suffix.

        Raises:
            ValueError: If the suffix is empty or contains unsafe characters.
        """
        normalized: str = suffix.lower()
        if not _TOKEN_PATTERN.fullmatch(normalized):
            raise ValueError("plugin suffix must be a non-empty lowercase token")
        return normalized

    def _snake_namespace(self) -> str:
        """Return the underscore form used by tool and Python identifiers.

        Returns:
            str: Namespace with hyphens normalized to underscores.
        """
        return self.namespace.replace("-", "_")
