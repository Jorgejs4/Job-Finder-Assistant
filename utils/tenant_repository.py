"""Typed, tenant-scoped persistence operations for Supabase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class TenantRepositoryError(RuntimeError):
    """Raised when a tenant-scoped Supabase operation fails."""


class TenantOwnershipError(TenantRepositoryError):
    """Raised when an object does not belong to the current tenant."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    user_id: str | None = None


class UserProfile(_Record):
    email: str = ""
    full_name: str = ""
    avatar_url: str = ""
    google_subject: str | None = None
    cv_path: str | None = None
    cv_hash: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class Job(_Record):
    canonical_url: str = ""
    source: str = ""
    source_job_id: str | None = None
    title: str = ""
    company: str = ""
    location: str | None = None
    description: str | None = None
    date_posted: str | None = None
    status: str = "Nuevo"
    archived: bool = False
    archive_reason: str | None = None
    content_hash: str | None = None
    analysis_hash: str | None = None
    analysis: dict[str, Any] | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    missing_streak: int = 0
    sync_status: str = "active"
    invalidated_at: str | None = None
    invalid_reason: str | None = None


class JobRun(_Record):
    run_key: str = ""
    status: str = "running"
    started_at: str | None = None
    finished_at: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    errors: list[Any] = Field(default_factory=list)


class Feedback(_Record):
    job_id: str | None = None
    feedback: str
    status: str = "pending"
    completed_at: str | None = None


class NotionConnection(_Record):
    workspace_id: str | None = None
    workspace_name: str | None = None
    database_id: str
    access_token: str | None = None


class CachedAnalysis(BaseModel):
    job_id: str
    content_hash: str
    analysis_hash: str
    analysis: dict[str, Any] | None = None


T = TypeVar("T", bound=BaseModel)


class TenantRepository:
    """Repository whose every read/update/delete is constrained to one user."""

    def __init__(self, client: Any, user_id: str):
        self.client = client
        self.user_id = str(user_id or "").strip()
        if not self.user_id:
            raise TenantRepositoryError("Se requiere un user_id autenticado para acceder al repositorio.")

    def _query(self, table: str):
        # Keep this constraint at the repository boundary, even with a service-role client.
        return self.client.table(table).select("*").eq("user_id", self.user_id)

    def _profile_query(self):
        # user_profiles uses the auth user UUID as its primary key, named `id`.
        return self.client.table("user_profiles").select("*").eq("id", self.user_id)

    @staticmethod
    def _data(response: Any) -> list[dict[str, Any]]:
        data = getattr(response, "data", response)
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        return list(data)

    def _execute(self, query: Any, operation: str) -> list[dict[str, Any]]:
        try:
            return self._data(query.execute())
        except Exception as exc:
            raise TenantRepositoryError(f"Error Supabase en {operation}: {exc}") from exc

    def _owned_payload(self, model: BaseModel) -> dict[str, Any]:
        payload = model.model_dump(exclude_none=True)
        payload.pop("user_id", None)
        payload["user_id"] = self.user_id
        return payload

    @staticmethod
    def _one(rows: list[dict[str, Any]], model: type[T]) -> T | None:
        return model.model_validate(rows[0]) if rows else None

    def get_profile(self) -> UserProfile | None:
        return self._one(self._execute(self._profile_query(), "leer perfil"), UserProfile)

    def get_profile_by_google_subject(self, subject: str) -> UserProfile | None:
        rows = self._execute(
            self.client.table("user_profiles").select("*").eq("google_subject", subject).limit(1),
            "buscar perfil OIDC",
        )
        return self._one(rows, UserProfile)

    def upsert_profile(self, profile: UserProfile | dict[str, Any]) -> UserProfile:
        model = profile if isinstance(profile, UserProfile) else UserProfile.model_validate(profile)
        payload = model.model_dump(exclude_none=True)
        # user_profiles is keyed by id, unlike tenant-owned child tables.
        payload.pop("user_id", None)
        payload["id"] = self.user_id
        rows = self._execute(self.client.table("user_profiles").upsert(payload, on_conflict="id"), "guardar perfil")
        return self._one(rows, UserProfile) or UserProfile.model_validate(payload)

    def upsert_schedule(self, config: dict[str, Any], next_run_at: str, enabled: bool = True) -> dict[str, Any]:
        payload = {
            "user_id": self.user_id,
            "config": dict(config),
            "next_run_at": next_run_at,
            "enabled": bool(enabled),
        }
        rows = self._execute(
            self.client.table("workflow_schedules").upsert(payload, on_conflict="user_id"),
            "guardar programación",
        )
        return rows[0] if rows else payload

    def list_jobs(self, *, status: str | None = None, include_archived: bool = True) -> list[Job]:
        query = self._query("jobs")
        if status:
            query = query.eq("status", status)
        if not include_archived:
            query = query.eq("archived", False)
        return [Job.model_validate(row) for row in self._execute(query, "listar jobs")]

    def get_job(self, job_id: str) -> Job | None:
        rows = self._execute(self._query("jobs").eq("id", str(job_id)), "leer job")
        return self._one(rows, Job)

    def upsert_job(self, job: Job | dict[str, Any]) -> Job:
        model = job if isinstance(job, Job) else Job.model_validate(job)
        payload = self._owned_payload(model)
        # The natural key owns the upsert. Never let an incoming primary key
        # target a row that belongs to another tenant.
        payload.pop("id", None)
        existing = self._execute(
            self._query("jobs").eq("canonical_url", model.canonical_url).limit(1),
            "buscar job existente",
        )
        if existing:
            # Scraper observations must not reset user-owned state or a prior
            # analysis. Those fields are changed only by explicit operations.
            for key in ("status", "archived", "archive_reason", "analysis", "analysis_hash"):
                payload.pop(key, None)
            rows = self._execute(
                self.client.table("jobs").update(payload)
                .eq("user_id", self.user_id)
                .eq("id", existing[0]["id"]),
                "actualizar observación de job",
            )
            return self._one(rows, Job) or Job.model_validate({**existing[0], **payload})
        rows = self._execute(
            self.client.table("jobs").upsert(payload, on_conflict="user_id,canonical_url"),
            "guardar job",
        )
        return self._one(rows, Job) or Job.model_validate(payload)

    def mark_missing(self, observed_urls: set[str], completed_sources: set[str]) -> int:
        """Record absence only for sources whose complete query succeeded."""
        if not completed_sources:
            return 0
        count = 0
        for job in self.list_jobs(include_archived=True):
            source_family = job.source.split("/", 1)[0]
            if source_family not in completed_sources or job.canonical_url in observed_urls:
                continue
            if job.sync_status == "invalidated_by_user":
                continue
            self.update_job(job.id, {
                "missing_streak": job.missing_streak + 1,
                "sync_status": "missing",
            })
            count += 1
        return count

    def update_job(self, job_id: str, updates: dict[str, Any]) -> Job:
        if "user_id" in updates:
            raise TenantOwnershipError("user_id no se puede modificar desde el repositorio.")
        payload = dict(updates)
        payload.pop("id", None)
        query = (
            self.client.table("jobs")
            .update(payload)
            .eq("user_id", self.user_id)
            .eq("id", str(job_id))
        )
        rows = self._execute(
            query,
            "actualizar job",
        )
        return self._one(rows, Job) or self.get_job(str(job_id)) or self._missing("job", job_id)

    def _missing(self, kind: str, object_id: Any):
        raise TenantOwnershipError(f"{kind} {object_id} no existe o no pertenece al usuario actual.")

    def get_cached_analysis(self, content_hash: str, analysis_hash: str) -> CachedAnalysis | None:
        query = self._query("jobs").eq("content_hash", content_hash).eq("analysis_hash", analysis_hash).limit(1)
        rows = self._execute(query, "leer caché de análisis")
        if not rows:
            return None
        row = rows[0]
        return CachedAnalysis(
            job_id=str(row["id"]),
            content_hash=str(row.get("content_hash", "")),
            analysis_hash=str(row.get("analysis_hash", "")),
            analysis=row.get("analysis"),
        )

    # Alias that reads naturally at call sites.
    find_cached_analysis = get_cached_analysis

    def save_analysis_cache(
        self, job_id: str, content_hash: str, analysis_hash: str, analysis: dict[str, Any]
    ) -> Job:
        return self.update_job(
            job_id,
            {"content_hash": content_hash, "analysis_hash": analysis_hash, "analysis": analysis},
        )

    def create_run(self, run: JobRun | dict[str, Any]) -> JobRun:
        model = run if isinstance(run, JobRun) else JobRun.model_validate(run)
        payload = self._owned_payload(model)
        payload.pop("id", None)
        payload.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        rows = self._execute(
            self.client.table("job_runs").upsert(payload, on_conflict="user_id,run_key"),
            "crear ejecución",
        )
        return self._one(rows, JobRun) or JobRun.model_validate(payload)

    def list_runs(self) -> list[JobRun]:
        return [JobRun.model_validate(row) for row in self._execute(self._query("job_runs"), "listar ejecuciones")]

    def get_run(self, run_id: str) -> JobRun | None:
        rows = self._execute(self._query("job_runs").eq("id", str(run_id)), "leer ejecución")
        return self._one(rows, JobRun)

    def list_run_job_ids(self, run_id: str) -> list[str]:
        rows = self._execute(
            self._query("run_jobs").select("job_id").eq("run_id", str(run_id)),
            "listar ofertas de ejecución",
        )
        return [str(row.get("job_id")) for row in rows if row.get("job_id")]

    def finish_run(self, run_id: str, *, status: str, stats: dict[str, Any] | None = None, errors: list[Any] | None = None) -> JobRun:
        payload: dict[str, Any] = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        if stats is not None:
            payload["stats"] = stats
        if errors is not None:
            payload["errors"] = errors
        rows = self._execute(
            self.client.table("job_runs").update(payload)
            .eq("user_id", self.user_id)
            .eq("id", str(run_id)),
            "finalizar ejecución",
        )
        return self._one(rows, JobRun) or self.get_run(run_id) or self._missing("ejecución", run_id)

    def attach_jobs_to_run(self, run_id: str, job_ids: list[str]) -> int:
        if not self.get_run(run_id):
            raise TenantOwnershipError(f"La ejecución {run_id} no pertenece al usuario actual.")
        rows = []
        for job_id in dict.fromkeys(str(value) for value in job_ids):
            if not self.get_job(job_id):
                raise TenantOwnershipError(f"El job {job_id} no pertenece al usuario actual.")
            rows.append({"user_id": self.user_id, "run_id": str(run_id), "job_id": job_id})
        if not rows:
            return 0
        self._execute(self.client.table("run_jobs").upsert(rows, on_conflict="user_id,run_id,job_id"), "vincular jobs")
        return len(rows)

    def sync_jobs(self, run_id: str, jobs: list[Job | dict[str, Any]]) -> list[Job]:
        if not self.get_run(run_id):
            raise TenantOwnershipError(f"La ejecución {run_id} no pertenece al usuario actual.")
        saved = [self.upsert_job(job) for job in jobs]
        self.attach_jobs_to_run(run_id, [job.id for job in saved if job.id])
        return saved

    def create_feedback(self, feedback: Feedback | dict[str, Any]) -> Feedback:
        model = feedback if isinstance(feedback, Feedback) else Feedback.model_validate(feedback)
        if model.job_id and not self.get_job(model.job_id):
            raise TenantOwnershipError(f"El job {model.job_id} no pertenece al usuario actual.")
        payload = self._owned_payload(model)
        payload.pop("id", None)
        rows = self._execute(self.client.table("feedback").insert(payload), "guardar feedback")
        return self._one(rows, Feedback) or Feedback.model_validate(payload)

    def list_feedback(self, *, status: str | None = None) -> list[Feedback]:
        query = self._query("feedback")
        if status:
            query = query.eq("status", status)
        return [Feedback.model_validate(row) for row in self._execute(query, "listar feedback")]

    def complete_feedback(self, feedback_id: str) -> Feedback:
        query = (
            self.client.table("feedback")
            .update({"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()})
            .eq("user_id", self.user_id)
            .eq("id", str(feedback_id))
        )
        rows = self._execute(
            query,
            "completar feedback",
        )
        return self._one(rows, Feedback) or next(
            (item for item in self.list_feedback() if item.id == str(feedback_id)),
            None,
        ) or self._missing("feedback", feedback_id)

    def upsert_notion_connection(self, connection: NotionConnection | dict[str, Any]) -> NotionConnection:
        model = connection if isinstance(connection, NotionConnection) else NotionConnection.model_validate(connection)
        payload = self._owned_payload(model)
        payload.pop("id", None)
        rows = self._execute(
            self.client.table("notion_connections").upsert(
                payload, on_conflict="user_id,database_id"
            ),
            "guardar conexión Notion",
        )
        return self._one(rows, NotionConnection) or NotionConnection.model_validate(payload)

    def list_notion_connections(self) -> list[NotionConnection]:
        return [
            NotionConnection.model_validate(row)
            for row in self._execute(self._query("notion_connections"), "listar conexiones Notion")
        ]
