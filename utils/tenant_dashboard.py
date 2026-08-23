"""Dashboard adapters backed by the tenant-scoped Supabase repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from utils.tenant_repository import Feedback, TenantRepository


def _job_dict(job) -> dict[str, Any]:
    raw = dict(job.raw_data or {})
    raw.update(job.analysis or {})
    raw.update(
        {
            "id": job.id,
            "user_id": job.user_id,
            "link": job.canonical_url,
            "canonical_url": job.canonical_url,
            "source": job.source,
            "title": job.title,
            "company": job.company,
            "location": job.location or "",
            "description": job.description or "",
            "date_posted": job.date_posted or "",
            "status": job.status,
            "archived": job.archived,
            "archive_reason": job.archive_reason,
            "missing_streak": job.missing_streak,
            "sync_status": job.sync_status,
            "invalidated_at": job.invalidated_at,
            "invalid_reason": job.invalid_reason,
            "needs_analysis": not bool(job.analysis_hash and job.analysis),
            "_first_seen": job.created_at,
            "_last_seen": job.updated_at,
        }
    )
    return raw


class TenantDashboardDB:
    """Small compatibility adapter for the existing Streamlit views."""

    def __init__(self, repository: TenantRepository):
        self.repository = repository
        self.db_path = "supabase"

    def get_all_jobs(self) -> list[dict[str, Any]]:
        return [_job_dict(job) for job in self.repository.list_jobs()]

    def get_all_runs(self) -> list[dict[str, Any]]:
        runs = []
        for run in self.repository.list_runs():
            row = run.model_dump()
            row["run_id"] = row.get("id")
            row["timestamp"] = row.get("started_at") or ""
            row["scraper_stats"] = row.get("stats") or {}
            row["errors"] = row.get("errors") or []
            row["jobs"] = []
            runs.append(row)
        return runs

    def get_job_count(self) -> int:
        return len(self.repository.list_jobs())

    def update_job_status(self, job_id: str, status: str) -> bool:
        self.repository.update_job(job_id, {"status": status})
        return True

    def update_job_archived(self, job_id: str, archived: bool, reason: str = None) -> bool:
        self.repository.update_job(
            job_id,
            {"archived": bool(archived), "archive_reason": reason},
        )
        return True

    def update_job(self, job_id: str, updates: dict[str, Any]):
        return self.repository.update_job(job_id, updates)

    def update_job_analysis(self, job_id: str, updates: dict[str, Any]) -> bool:
        self.repository.update_job(job_id, updates)
        return True

    def export_data_json(self, *_args, **_kwargs):
        # Supabase is canonical in tenant mode; never export private data to GitHub.
        return None

    def get_history(self) -> list[dict[str, Any]]:
        return []


class TenantFeedbackManager:
    """Feedback adapter with the same methods used by the legacy dashboard."""

    def __init__(self, repository: TenantRepository):
        self.repository = repository

    def has_pending(self, title: str, company: str) -> bool:
        jobs = {
            job.id for job in self.repository.list_jobs()
            if job.title == title and job.company == company
        }
        return any(item.job_id in jobs for item in self.repository.list_feedback(status="pending"))

    def save_feedback(self, title: str, company: str, feedback_text: str) -> str:
        matches = [
            job for job in self.repository.list_jobs()
            if job.title == title and job.company == company
        ]
        if not matches:
            raise ValueError("La oferta ya no existe en la cuenta actual.")
        feedback = self.repository.create_feedback(
            Feedback(job_id=matches[0].id, feedback=feedback_text.strip())
        )
        return str(feedback.id)

    def get_pending(self):
        return [item.model_dump() for item in self.repository.list_feedback(status="pending")]
