"""Offline tests for validated tenant workflow boundaries."""

import json
import pytest

from utils.workflow_config import WorkflowConfig
from utils.workflow_dispatch import WorkflowDispatchError, dispatch_workflow
from worker.tenant_worker import TenantWorker
from tests.test_multitenant import FakeClient


def test_workflow_config_defaults_and_rejects_unknown_or_invalid_values():
    settings = WorkflowConfig()
    assert settings.locations == ["Sevilla", "Remoto"]
    assert settings.max_jobs_per_scraper == 250
    with pytest.raises(ValueError):
        WorkflowConfig.model_validate({"workers": 0})
    with pytest.raises(ValueError):
        WorkflowConfig.model_validate({"unexpected": True})


class FakeResponse:
    status_code = 204


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_dispatch_uses_server_token_and_only_validated_inputs(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "server-token")
    client = FakeHttpClient()
    dispatch_workflow("user-a", {"locations": ["Remote"]}, repository="owner/repo", client=client)
    url, request = client.calls[0]
    assert url.endswith("tenant-scrape.yml/dispatches")
    assert request["headers"]["Authorization"] == "Bearer server-token"
    assert request["json"]["inputs"]["user_id"] == "user-a"
    assert json.loads(request["json"]["inputs"]["config_json"])["locations"] == ["Remote"]


def test_dispatch_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(WorkflowDispatchError):
        dispatch_workflow("user-a", repository="owner/repo", client=FakeHttpClient())


class FakeScraper:
    def scrape_jobs(self, query, locations):
        assert query == ""
        return [{"link": "https://jobs.test/1", "title": "Python developer", "description": "Python"}]


def test_tenant_worker_scopes_data_and_reuses_hash_cache():
    calls = []

    def analyzer(job, settings):
        calls.append(job.canonical_url)
        return {"match_score": 90}

    worker = TenantWorker(FakeClient(), "user-a", scrapers=[FakeScraper()], analyzer=analyzer)
    result = worker.run({"locations": ["Remote"], "use_jobspy": False})
    assert result["analyzed"] == 1
    assert calls == ["https://jobs.test/1"]
