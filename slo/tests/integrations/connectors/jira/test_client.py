"""Tests for JiraAPIClient (25.a.3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from src.integrations.connectors.credentials import (
    ConnectorCredentialDAO,
    ConnectorProviderName,
)
from src.integrations.connectors.exceptions import ConnectorCredentialsRequiredError
from src.integrations.connectors.jira.client import JiraAPIClient
from src.integrations.connectors.jira.dao import JiraIssueDAO, JiraIssueSummaryDAO
from src.integrations.connectors.jira.exceptions import JiraAPIError


def _clear_atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("SLO_ATLASSIAN_SITE_URL", "SLO_ATLASSIAN_EMAIL", "SLO_ATLASSIAN_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


class TestJiraAPIClientInit:
    def test_raises_when_no_credentials(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_atlassian_env(monkeypatch)
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))

        with pytest.raises(ConnectorCredentialsRequiredError):
            JiraAPIClient()


def _make_issue_row(key: str = "SLO-1", summary: str = "Fix bug") -> dict:
    return {
        "id": "1001",
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": "Story"},
            "status": {"name": "To Do"},
            "project": {"key": "SLO"},
            "assignee": None,
            "description": None,
            "parent": None,
        },
    }


class TestJiraAPIClientSearch:
    def test_search_calls_correct_endpoint(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request("/rest/api/3/search", method="GET").respond_with_json(
            {"issues": [_make_issue_row()]}
        )

        client = JiraAPIClient()
        results = asyncio.run(client.search_issues(jql="project=SLO", limit=5))

        assert len(results) == 1
        assert isinstance(results[0], JiraIssueSummaryDAO)
        assert results[0].issue_key == "SLO-1"
        assert results[0].summary == "Fix bug"

    def test_search_returns_empty_on_no_results(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request("/rest/api/3/search", method="GET").respond_with_json({"issues": []})

        client = JiraAPIClient()
        results = asyncio.run(client.search_issues(jql="project=NONE"))

        assert results == []

    def test_search_raises_on_401(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request("/rest/api/3/search", method="GET").respond_with_data(
            "Unauthorized", status=401
        )

        client = JiraAPIClient()
        with pytest.raises(JiraAPIError) as exc_info:
            asyncio.run(client.search_issues(jql="project=SLO"))

        assert exc_info.value.status_code == 401


class TestJiraAPIClientGetIssue:
    def test_get_issue_fetches_correct_endpoint(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request("/rest/api/3/issue/SLO-42", method="GET").respond_with_json(
            _make_issue_row(key="SLO-42", summary="New feature")
        )

        client = JiraAPIClient()
        issue = asyncio.run(client.get_issue(issue_key="SLO-42"))

        assert isinstance(issue, JiraIssueDAO)
        assert issue.issue_key == "SLO-42"
        assert issue.summary == "New feature"
        assert issue.issue_type == "Story"
        assert issue.project_key == "SLO"

    def test_get_issue_raises_on_404(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request("/rest/api/3/issue/MISSING-1", method="GET").respond_with_data(
            "Not Found", status=404
        )

        client = JiraAPIClient()
        with pytest.raises(JiraAPIError) as exc_info:
            asyncio.run(client.get_issue(issue_key="MISSING-1"))

        assert exc_info.value.status_code == 404


class TestJiraAPIClientCreateIssue:
    def test_create_posts_payload_and_fetches_created_issue(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        httpserver.expect_request("/rest/api/3/issue", method="POST").respond_with_json(
            {"id": "2001", "key": "SLO-55"}, status=201
        )

        httpserver.expect_request("/rest/api/3/issue/SLO-55", method="GET").respond_with_json(
            _make_issue_row(key="SLO-55", summary="Brand new issue")
        )

        from src.integrations.connectors.jira.dao import JiraIssueCreateRequestDAO

        client = JiraAPIClient()
        issue = asyncio.run(
            client.create_issue(
                request=JiraIssueCreateRequestDAO(
                    project_key="SLO",
                    issue_type_name="Story",
                    summary="Brand new issue",
                )
            )
        )

        assert isinstance(issue, JiraIssueDAO)
        assert issue.issue_key == "SLO-55"

    def test_create_includes_description_as_adf(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The create POST body includes an ADF description when text is given."""
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        received_bodies: list[dict] = []

        def _handler(request):  # type: ignore[no-untyped-def]
            received_bodies.append(request.json)
            from werkzeug.wrappers import Response

            return Response(
                json.dumps({"id": "3001", "key": "SLO-66"}),
                status=201,
                content_type="application/json",
            )

        httpserver.expect_request("/rest/api/3/issue", method="POST").respond_with_handler(_handler)

        httpserver.expect_request("/rest/api/3/issue/SLO-66", method="GET").respond_with_json(
            _make_issue_row(key="SLO-66", summary="With desc")
        )

        from src.integrations.connectors.jira.dao import JiraIssueCreateRequestDAO

        client = JiraAPIClient()
        asyncio.run(
            client.create_issue(
                request=JiraIssueCreateRequestDAO(
                    project_key="SLO",
                    issue_type_name="Story",
                    summary="With desc",
                    description="Some description text",
                )
            )
        )

        assert len(received_bodies) == 1
        body = received_bodies[0]
        desc = body["fields"]["description"]
        assert desc["type"] == "doc"
        assert desc["content"][0]["content"][0]["text"] == "Some description text"

    def test_create_with_parent_key_includes_parent_field(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SLO_CONNECTORS_DIR", str(tmp_path))
        monkeypatch.setenv("SLO_ATLASSIAN_SITE_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setenv("SLO_ATLASSIAN_EMAIL", "u@e.com")
        monkeypatch.setenv("SLO_ATLASSIAN_API_TOKEN", "tok")

        received_bodies: list[dict] = []

        def _handler(request):  # type: ignore[no-untyped-def]
            received_bodies.append(request.json)
            from werkzeug.wrappers import Response

            return Response(
                json.dumps({"id": "4001", "key": "SLO-77"}),
                status=201,
                content_type="application/json",
            )

        httpserver.expect_request("/rest/api/3/issue", method="POST").respond_with_handler(_handler)

        sub_row = _make_issue_row(key="SLO-77", summary="Sub-task")
        sub_row["fields"]["parent"] = {"key": "SLO-1"}
        httpserver.expect_request("/rest/api/3/issue/SLO-77", method="GET").respond_with_json(sub_row)

        from src.integrations.connectors.jira.dao import JiraIssueCreateRequestDAO

        client = JiraAPIClient()
        issue = asyncio.run(
            client.create_issue(
                request=JiraIssueCreateRequestDAO(
                    project_key="SLO",
                    issue_type_name="Sub-task",
                    summary="Sub-task",
                    parent_issue_key="SLO-1",
                )
            )
        )

        body = received_bodies[0]
        assert body["fields"]["parent"]["key"] == "SLO-1"
        assert issue.parent_issue_key == "SLO-1"


class TestJiraAPIClientADFConversion:
    def test_to_adf_structure(self) -> None:
        adf = JiraAPIClient._to_adf(text="Hello world")
        assert adf["version"] == 1
        assert adf["type"] == "doc"
        assert adf["content"][0]["type"] == "paragraph"
        assert adf["content"][0]["content"][0]["text"] == "Hello world"
