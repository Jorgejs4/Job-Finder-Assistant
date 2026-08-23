"""Tenant-isolated scrape/analyse runner. It never touches legacy files."""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utils.tenant_repository import Job, JobRun, TenantRepository
from utils.workflow_config import WorkflowConfig


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class TenantWorker:
    def __init__(
        self,
        client: Any,
        user_id: str,
        *,
        scrapers: Iterable[Any] = (),
        analyzer: Callable[..., Any] | None = None,
        cv_loader: Callable[[str], str] | None = None,
    ):
        self.repo = TenantRepository(client, user_id)
        self.scrapers = list(scrapers)
        self.analyzer = analyzer
        self.cv_loader = cv_loader
        self.cv_text = ""

    def run(self, config: WorkflowConfig | dict[str, Any] | None = None, *, reanalyze: bool | None = None) -> dict[str, int]:
        settings = WorkflowConfig.from_mapping(config)
        do_reanalyze = settings.reanalyze if reanalyze is None else reanalyze
        profile = self.repo.get_profile()
        if profile and profile.cv_path and self.cv_loader:
            self.cv_text = self.cv_loader(profile.cv_path)
        run = self.repo.create_run(JobRun(run_key=_hash({"config": settings.model_dump(), "reanalyze": do_reanalyze})))
        collected: list[dict[str, Any]] = []
        completed_sources: set[str] = set()
        if not do_reanalyze:
            for scraper in self.scrapers:
                try:
                    results = scraper.scrape_jobs("", settings.locations) or []
                    collected.extend(results[: settings.max_jobs_per_scraper])
                    for item in results:
                        source = str(item.get("source", "")).split("/", 1)[0]
                        if source:
                            completed_sources.add(source)
                except Exception as exc:
                    print(f"[Scraper] Error aislado: {exc}")
            jobs = [self._normalize(item) for item in collected if item.get("link") or item.get("canonical_url")]
            observed_urls = {job.canonical_url for job in jobs}
            saved = self.repo.sync_jobs(run.id, jobs)
            self.repo.mark_missing(observed_urls, completed_sources)
        else:
            saved = self.repo.list_jobs(include_archived=False)

        analyzed = 0
        cached = 0
        errors: list[str] = []
        limit = settings.reanalysis_limit if do_reanalyze else settings.max_gemini_jobs
        try:
            for job in saved:
                content_hash = _hash({"title": job.title, "company": job.company, "description": job.description, "url": job.canonical_url})
                analysis_hash = settings.analysis_hash()
                if job.content_hash == content_hash and job.analysis_hash == analysis_hash and job.analysis:
                    cached += 1
                    continue
                hit = self.repo.find_cached_analysis(content_hash, analysis_hash)
                if hit and hit.analysis:
                    self.repo.save_analysis_cache(job.id, content_hash, analysis_hash, hit.analysis)
                    cached += 1
                    continue
                if not self.analyzer:
                    continue
                try:
                    result = self.analyzer(job, settings)
                    analysis = result.model_dump() if hasattr(result, "model_dump") else dict(result)
                    self.repo.save_analysis_cache(job.id, content_hash, analysis_hash, analysis)
                    analyzed += 1
                except Exception as exc:
                    errors.append(f"{job.canonical_url}: {exc}")
                if limit and analyzed >= limit:
                    break
            self.repo.finish_run(
                run.id, status="completed",
                stats={"found": len(saved), "analyzed": analyzed, "cached": cached},
                errors=errors,
            )
        except Exception as exc:
            self.repo.finish_run(
                run.id, status="failed",
                stats={"found": len(saved), "analyzed": analyzed, "cached": cached},
                errors=errors + [str(exc)],
            )
            raise
        return {"found": len(saved), "analyzed": analyzed, "cached": cached, "errors": len(errors)}

    @staticmethod
    def _normalize(item: dict[str, Any]) -> Job:
        data = dict(item)
        data["canonical_url"] = TenantWorker._canonical_url(
            data.pop("canonical_url", data.pop("link", ""))
        )
        data.setdefault("source_job_id", data["canonical_url"])
        data.setdefault("raw_data", dict(item))
        return Job.model_validate(data)

    @staticmethod
    def _canonical_url(value: str) -> str:
        parsed = urlsplit(str(value or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(value or "").strip().rstrip("/")
        query = [
            (key, val) for key, val in parse_qsl(parsed.query)
            if not key.lower().startswith(("utm_", "ref", "src"))
        ]
        return urlunsplit((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"),
            urlencode(query), "",
        ))


def main() -> None:
    """CLI entry point used by Actions; all credentials come from environment secrets."""
    import json as json_module
    from scrapers.jobspy_scraper import JobSpyScraper
    from utils.gemini_client import GeminiClient
    from utils.cv_storage import CVStorage
    from utils.supabase_client import create_server_client

    user_id = os.environ.get("TENANT_USER_ID", "").strip()
    settings = WorkflowConfig.model_validate(json_module.loads(os.environ.get("TENANT_CONFIG_JSON", "{}")))
    if not user_id:
        raise SystemExit("TENANT_USER_ID es obligatorio")
    gemini = GeminiClient()

    client = create_server_client()

    def load_cv(path: str) -> str:
        data = CVStorage(client).download_cv(user_id, path)
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".pdf":
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
        if suffix == ".docx":
            import docx
            return "\n".join(paragraph.text for paragraph in docx.Document(BytesIO(data)).paragraphs)
        return data.decode("utf-8")

    from scrapers.infojobs_scraper import InfoJobsScraper
    from scrapers.linkedin_scraper import LinkedInScraper
    from scrapers.remotive_scraper import RemotiveScraper
    from scrapers.tecnobs_scraper import TecnoJobsScraper
    from scrapers.jooble_scraper import JoobleScraper
    from scrapers.getonbrd_scraper import GetOnBoardScraper
    from scrapers.jobfluent_scraper import JobfluentScraper

    worker_profile = TenantRepository(client, user_id).get_profile()
    if not worker_profile or not worker_profile.cv_path:
        raise SystemExit("El usuario no tiene un CV configurado.")
    cv_text = load_cv(worker_profile.cv_path)

    def analyze(job: Job, _settings: WorkflowConfig) -> dict[str, Any]:
        result = gemini.match_offer(
            cv_text, job.title, job.description or "",
            settings.years_of_experience,
        )
        return result.model_dump()
    roles = ["software developer"]
    if worker_profile and worker_profile.preferences.get("roles"):
        roles = worker_profile.preferences["roles"][:4]
    else:
        try:
            roles = gemini.analyze_cv(cv_text).recommended_roles[:4] or roles
        except Exception as exc:
            print(f"[Perfil] No se pudieron extraer roles: {exc}")

    scraper_classes = [
        InfoJobsScraper, LinkedInScraper, RemotiveScraper,
        TecnoJobsScraper, JoobleScraper, GetOnBoardScraper,
    ]
    if settings.use_jobspy:
        scraper_classes.append(lambda: JobSpyScraper(
            sites=settings.jobspy_sites,
            max_jobs=settings.max_jobs_per_scraper,
        ))
    if settings.headless:
        scraper_classes.append(JobfluentScraper)
    scrapers = [factory() for factory in scraper_classes]

    class RoleScraper:
        def __init__(self, scraper, role):
            self.scraper, self.role = scraper, role

        def scrape_jobs(self, _query, locations):
            return self.scraper.scrape_jobs(self.role, locations)

    role_scrapers = [RoleScraper(scraper, role) for role in roles for scraper in scrapers]
    worker = TenantWorker(
        client,
        user_id,
        scrapers=role_scrapers,
        analyzer=analyze,
        cv_loader=load_cv,
    )
    print(worker.run(settings))


if __name__ == "__main__":
    main()
