"""Migrate the legacy single-user JSON database into Supabase."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.cv_storage import CVStorage
from utils.supabase_client import create_server_client
from utils.tenant_repository import TenantRepository, UserProfile
from utils.workflow_config import WorkflowConfig


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "results" / "data.json"
FEEDBACK_PATH = ROOT / "results" / "feedback.json"
CV_PATH = ROOT / "cv.pdf"
NAMESPACE = uuid.UUID("4f3dbe3f-29cc-4ed3-b77b-c5c1a0cb1f50")


def canonical_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(value or "").strip().rstrip("/")
    query = [(key, val) for key, val in parse_qsl(parsed.query)
             if not key.lower().startswith(("utm_", "ref", "src"))]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path.rstrip("/"), urlencode(query), ""))


def stable_id(user_id: str, value: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{user_id}:{value}"))


def is_test_job(job: dict[str, Any]) -> bool:
    values = " ".join(str(job.get(key, "")) for key in ("title", "company", "_scraper", "source"))
    return bool(re.search(r"test(scraper| job)?", values, re.IGNORECASE))


def load_legacy(source_ref: str | None = None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if source_ref:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{source_ref}:results/data.json"],
                cwd=ROOT,
            )
            data = json.loads(raw.decode("utf-8"))
        except (subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"No se pudo leer results/data.json desde Git ({source_ref}): {exc}") from exc
    else:
        if not DATA_PATH.exists():
            raise SystemExit(f"No existe {DATA_PATH}")
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    jobs: dict[str, dict[str, Any]] = {}
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            if is_test_job(job):
                continue
            url = canonical_url(job.get("link", ""))
            if url:
                jobs.setdefault(url, dict(job))
    return data, jobs


def analysis_payload(job: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "match_score", "tech_stack", "work_mode", "salary", "salary_is_estimate",
        "required_experience", "tailored_advice", "cover_letter", "cv_summary",
        "cv_experience_adapted", "cv_skills", "cv_projects", "interview_prep",
        "company_profile", "project_match", "language", "custom_cv_url",
        "custom_cv_html", "cover_letter_pdf_url",
    )
    return {key: job[key] for key in keys if job.get(key) is not None}


def job_payload(user_id: str, url: str, job: dict[str, Any]) -> dict[str, Any]:
    content = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "description": job.get("description", ""),
        "url": url,
    }
    content_hash = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
    source = str(job.get("source", "") or job.get("_scraper", "legacy"))
    return {
        "id": stable_id(user_id, url),
        "user_id": user_id,
        "canonical_url": url,
        "source": source,
        "source_job_id": url,
        "title": str(job.get("title", "")),
        "company": str(job.get("company", "")),
        "location": job.get("location"),
        "description": job.get("description"),
        "date_posted": job.get("date_posted"),
        "status": job.get("status") or "Nuevo",
        "archived": bool(job.get("archived")),
        "archive_reason": job.get("archive_reason"),
        "content_hash": content_hash,
        "analysis_hash": "legacy-import" if job.get("match_score") is not None else None,
        "analysis": analysis_payload(job) or None,
        "raw_data": job,
        "missing_streak": 0,
        "sync_status": "active",
    }


def upsert_batches(client: Any, table: str, rows: list[dict[str, Any]], conflict: str, batch_size: int = 100) -> None:
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        if batch:
            client.table(table).upsert(batch, on_conflict=conflict).execute()


def migrate(user_id: str, *, upload_artifacts: bool = True, source_ref: str | None = None) -> dict[str, int]:
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise SystemExit("--user-id debe ser un UUID de Supabase auth.users") from exc
    user_id = str(user_uuid)
    data, jobs_by_url = load_legacy(source_ref)
    client = create_server_client()
    repo = TenantRepository(client, user_id)
    profile = repo.get_profile() or UserProfile(id=user_id)
    prefs = dict(profile.preferences or {})
    prefs.setdefault("workflow", WorkflowConfig().model_dump())
    profile = repo.upsert_profile(profile.model_copy(update={"preferences": prefs}))

    jobs = [job_payload(user_id, url, job) for url, job in jobs_by_url.items()]
    upsert_batches(client, "jobs", jobs, "user_id,canonical_url")
    # run_jobs.job_id must reference the UUID generated for the migrated job,
    # not the legacy short/hash id that may exist inside data.json.
    id_by_url = {url: payload["id"] for url, payload in zip(jobs_by_url, jobs)}

    runs = []
    run_jobs = []
    for run in data.get("runs", []):
        run_key = str(run.get("run_id", ""))
        if not run_key or run_key == "_orphan":
            continue
        run_id = stable_id(user_id, f"run:{run_key}")
        runs.append({
            "id": run_id,
            "user_id": user_id,
            "run_key": run_key,
            "status": "completed",
            "started_at": run.get("timestamp") or None,
            "finished_at": run.get("timestamp") or None,
            "stats": run.get("scraper_stats") or {},
            "errors": run.get("errors") or [],
        })
        for job in run.get("jobs", []):
            url = canonical_url(job.get("link", ""))
            if url in id_by_url:
                run_jobs.append({"user_id": user_id, "run_id": run_id, "job_id": id_by_url[url]})
    upsert_batches(client, "job_runs", runs, "user_id,run_key")
    upsert_batches(client, "run_jobs", run_jobs, "user_id,run_id,job_id")

    feedback_count = 0
    if FEEDBACK_PATH.exists():
        feedback_data = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        feedback_rows = []
        for item in feedback_data.get("pending", []):
            matches = [url for url, job in jobs_by_url.items()
                       if job.get("title") == item.get("title") and job.get("company") == item.get("company")]
            if matches:
                feedback_rows.append({
                    "user_id": user_id,
                    "job_id": id_by_url[matches[0]],
                    "feedback": item.get("feedback", ""),
                    "status": "pending",
                })
        upsert_batches(client, "feedback", feedback_rows, "id")
        feedback_count = len(feedback_rows)

    artifact_count = 0
    if upload_artifacts and CV_PATH.exists():
        storage = CVStorage(client)
        cv_path = storage.upload_cv(user_id, CV_PATH.read_bytes(), CV_PATH.name, content_type="application/pdf")
        repo.upsert_profile(profile.model_copy(update={"cv_path": cv_path, "cv_hash": hashlib.sha256(CV_PATH.read_bytes()).hexdigest()}))
        artifact_count += 1

    return {
        "jobs": len(jobs), "runs": len(runs), "run_jobs": len(run_jobs),
        "feedback": feedback_count, "artifacts": artifact_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrar datos legacy a Supabase")
    parser.add_argument("--user-id", default=os.getenv("MIGRATION_USER_ID"), help="UUID de auth.users")
    parser.add_argument("--skip-artifacts", action="store_true", help="No subir el CV original")
    parser.add_argument("--dry-run", action="store_true", help="Solo contar y validar datos locales")
    parser.add_argument("--source-ref", help="Commit/tag de Git desde el que leer results/data.json")
    args = parser.parse_args()
    if args.dry_run:
        data, jobs = load_legacy(args.source_ref)
        runs = [run for run in data.get("runs", []) if run.get("run_id") and run.get("run_id") != "_orphan"]
        print(json.dumps({"jobs": len(jobs), "runs": len(runs)}, indent=2))
        return
    if not args.user_id:
        parser.error("falta --user-id o MIGRATION_USER_ID")
    print(json.dumps(migrate(
        args.user_id,
        upload_artifacts=not args.skip_artifacts,
        source_ref=args.source_ref,
    ), indent=2))


if __name__ == "__main__":
    main()
