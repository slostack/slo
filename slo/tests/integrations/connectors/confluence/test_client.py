"""Tests for ConfluenceAPIClient (25.a.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from src.integrations.connectors.credentials import (
    ConnectorCredentialDAO,
    ConnectorProviderName,
)
from src.integrations.connectors.confluence.client import ConfluenceAPIClient
from src.integrations.connectors.confluence.dao import (
    ConfluencePageDAO,
    ConfluencePageSummaryDAO,
)
from src.integrations.connectors.confluence.exceptions import ConfluenceAPIError
from src.integrations.connectors.exceptions import ConnectorCredentialsRequiredError


def _atlassian_cred(base_url: str) -> ConnectorCredentialDAO:
    return ConnectorCredentialDAO(
        provider=ConnectorProviderName.ATLASSIAN,
        base_url=base_url,
        token="tok",
        username="user@example.com",
        timeout_seconds=5.0,
    )


class TestConfluenceAPIClientInit:
    """Constructor raises when credentials are missing."""

    def test_raises_when_no_credentials(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        for var in (
            "SLO_ATLASSIAN_SITE_URL",
            "SLO_ATLASSIAN_EMAIL",
            "SLO_ATLASSIAN_API_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        with pytest.raises(ConnectorCredentialsRequiredError):
            ConfluenceAPIClient()


class TestConfluenceAPIClientSearchPages:
    """``search_pages`` maps CQL search responses to ConfluencePageSummaryDAO."""

    def test_search_calls_correct_endpoint_with_params(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request(
            "/wiki/rest/api/search",
            method="GET",
            query_string="cql=type%3Dpage&limit=5",
        ).respond_with_json(
            {
                "results": [
                    {
                        "content": {"id": "111", "title": "Test Page", "type": "page"},
                        "url": "https://example.atlassian.net/wiki/spaces/TEST/pages/111",
                    }
                ]
            }
        )

        client = ConfluenceAPIClient()

        import asyncio

        results = asyncio.run(client.search_pages(cql="type=page", limit=5))

        assert len(results) == 1
        assert isinstance(results[0], ConfluencePageSummaryDAO)
        assert results[0].page_id == "111"
        assert results[0].title == "Test Page"

    def test_search_returns_empty_list_when_no_results(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request(
            "/wiki/rest/api/search",
            method="GET",
        ).respond_with_json({"results": []})

        client = ConfluenceAPIClient()

        import asyncio

        results = asyncio.run(client.search_pages(cql="type=page"))

        assert results == []

    def test_search_raises_api_error_on_non_2xx(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request(
            "/wiki/rest/api/search",
            method="GET",
        ).respond_with_data("Unauthorized", status=401)

        client = ConfluenceAPIClient()

        import asyncio

        with pytest.raises(ConfluenceAPIError) as exc_info:
            asyncio.run(client.search_pages(cql="type=page"))

        assert exc_info.value.status_code == 401


class TestConfluenceAPIClientGetPage:
    """``get_page`` maps pages-v2 API responses to ConfluencePageDAO."""

    def test_get_page_calls_correct_endpoint(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request(
            "/wiki/api/v2/pages/12345",
            method="GET",
        ).respond_with_json(
            {
                "id": "12345",
                "title": "My RFC",
                "_links": {"webui": "/wiki/spaces/ENG/pages/12345"},
                "body": {"storage": {"value": "<p>Hello</p>", "representation": "storage"}},
            }
        )

        client = ConfluenceAPIClient()

        import asyncio

        page = asyncio.run(client.get_page(page_id="12345"))

        assert isinstance(page, ConfluencePageDAO)
        assert page.page_id == "12345"
        assert page.title == "My RFC"
        assert page.body_value == "<p>Hello</p>"
        assert page.body_format == "storage"

    def test_get_page_uses_view_format_when_requested(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request(
            "/wiki/api/v2/pages/99",
            method="GET",
        ).respond_with_json(
            {
                "id": "99",
                "title": "Rendered",
                "body": {"view": {"value": "<b>text</b>"}},
            }
        )

        client = ConfluenceAPIClient()

        import asyncio

        page = asyncio.run(client.get_page(page_id="99", body_format="view"))

        assert page.body_format == "view"
        assert page.body_value == "<b>text</b>"

    def test_get_page_raises_api_error_on_404(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request(
            "/wiki/api/v2/pages/missing",
            method="GET",
        ).respond_with_data("Not Found", status=404)

        client = ConfluenceAPIClient()

        import asyncio

        with pytest.raises(ConfluenceAPIError) as exc_info:
            asyncio.run(client.get_page(page_id="missing"))

        assert exc_info.value.status_code == 404
