"""Tests for canonical managed-plugin identity derivation."""

from __future__ import annotations

import pytest

from src.agents.slo_agent.plugins.identity import PluginIdentityDAO


class TestPluginIdentityDAO:
    """Plugin public names derive from one normalized source identity."""

    def test_from_source_url_derives_normalized_identity_and_public_names(self) -> None:
        """A supported GitHub URL maps to every canonical namespace surface."""
        identity: PluginIdentityDAO = PluginIdentityDAO.from_source_url(
            source_url="https://github.com/Acme/deploy-tools.git/"
        )

        assert identity.source_url == "https://github.com/acme/deploy-tools"
        assert identity.plugin_id == "acme-deploy-tools"
        assert identity.namespace == "acme-deploy-tools"
        assert identity.module_name == "slo_plugin_acme_deploy_tools"
        assert identity.tool_name(suffix="deploy") == "acme_deploy_tools__deploy"
        assert identity.command_token(suffix="ship") == "/acme-deploy-tools:ship"
        assert identity.status_key(suffix="state") == "acme-deploy-tools:state"

    @pytest.mark.parametrize(
        "source_url",
        [
            "http://github.com/acme/tool",
            "https://example.com/acme/tool",
            "https://github.com/acme",
            "git@github.com:acme/tool.git",
        ],
    )
    def test_from_source_url_rejects_unsupported_source(self, source_url: str) -> None:
        """Only full HTTPS GitHub/GitLab owner-repository URLs are accepted."""
        with pytest.raises(ValueError, match="supported GitHub or GitLab HTTPS"):
            PluginIdentityDAO.from_source_url(source_url=source_url)

    @pytest.mark.parametrize("suffix", ["", "two words", "bad/slash"])
    def test_derived_name_rejects_unsafe_suffix(self, suffix: str) -> None:
        """Namespaced surface rejects empty or non-token plugin-local suffixes."""
        identity: PluginIdentityDAO = PluginIdentityDAO.from_source_url(
            source_url="https://gitlab.com/acme/tool"
        )

        with pytest.raises(ValueError, match="plugin suffix"):
            identity.tool_name(suffix=suffix)
