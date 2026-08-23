"""Offline tests for tenant isolation, cache keys and private CV paths."""

from types import SimpleNamespace

import pytest

from utils.cv_storage import CVStorage, CVStorageError
from utils.tenant_repository import TenantOwnershipError, TenantRepository


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table_name = db, table
        self.filters = []
        self.payload = None
        self.operation = "select"

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, *_):
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def upsert(self, payload, **_):
        self.operation, self.payload = "upsert", payload
        return self

    def execute(self):
        rows = self.db.setdefault(self.table_name, [])
        filters = dict(self.filters)
        if self.operation == "select":
            return SimpleNamespace(data=[row.copy() for row in rows if all(row.get(k) == v for k, v in filters.items())])
        payloads = self.payload if isinstance(self.payload, list) else [self.payload]
        result = []
        for payload in payloads:
            matching = next((row for row in rows if row.get("id") == payload.get("id") and payload.get("id")), None)
            if matching:
                matching.update(payload)
                result.append(matching.copy())
            else:
                row = payload.copy()
                row.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
                rows.append(row)
                result.append(row.copy())
        if self.operation == "update":
            result = []
            for row in rows:
                if all(row.get(k) == v for k, v in filters.items()):
                    row.update(self.payload)
                    result.append(row.copy())
        return SimpleNamespace(data=result)


class FakeClient:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return FakeQuery(self.db, name)


def test_repository_does_not_read_another_tenant_and_always_filters_owner():
    client = FakeClient()
    first = TenantRepository(client, "user-a")
    second = TenantRepository(client, "user-b")
    first.upsert_job({"canonical_url": "https://example.test/job", "title": "A"})
    assert second.list_jobs() == []
    assert first.list_jobs()[0].title == "A"


def test_cache_requires_both_hashes_and_is_tenant_scoped():
    client = FakeClient()
    repo = TenantRepository(client, "user-a")
    saved = repo.upsert_job({"canonical_url": "url", "content_hash": "content", "analysis_hash": "prompt", "analysis": {"score": 90}})
    cached = repo.get_cached_analysis("content", "prompt")
    assert cached and cached.job_id == saved.id and cached.analysis == {"score": 90}
    repo.save_analysis_cache(saved.id, "content", "prompt", {"score": 95})
    assert repo.get_cached_analysis("content", "prompt").analysis == {"score": 95}
    assert repo.get_cached_analysis("content", "other") is None
    assert TenantRepository(client, "user-b").get_cached_analysis("content", "prompt") is None


def test_attach_jobs_rejects_cross_tenant_job():
    client = FakeClient()
    owner = TenantRepository(client, "user-a")
    other = TenantRepository(client, "user-b")
    run = owner.create_run({"run_key": "run-1"})
    job = other.upsert_job({"canonical_url": "url"})
    with pytest.raises(TenantOwnershipError):
        owner.attach_jobs_to_run(run.id, [job.id])


class FakeBucket:
    def __init__(self):
        self.uploads = []

    def upload(self, path, data, options):
        self.uploads.append((path, data, options))

    def create_signed_url(self, path, expires):
        return {"signedURL": f"https://storage.test/{path}?expires={expires}"}


class FakeStorage:
    def __init__(self):
        self.bucket = FakeBucket()

    def from_(self, _):
        return self.bucket


def test_cv_storage_uses_private_owner_path_and_signed_url():
    client = SimpleNamespace(storage=FakeStorage())
    storage = CVStorage(client)
    path = storage.upload_cv("user-a", b"pdf", "cv.pdf")
    assert path.startswith("user-a/")
    assert storage.signed_url("user-a", path).startswith("https://storage.test/")
    with pytest.raises(CVStorageError):
        storage.signed_url("user-b", path)
