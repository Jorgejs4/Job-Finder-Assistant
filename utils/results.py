import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from utils.database import Database


class ResultsManager:
    def __init__(self, results_dir: str = None):
        if results_dir is None:
            results_dir = os.path.join(Path(__file__).resolve().parent.parent, "results")
        self.results_dir = results_dir
        os.makedirs(self.results_dir, exist_ok=True)
        self.data_path_legacy = os.path.join(self.results_dir, "data.json")
        self.pending_path = os.path.join(self.results_dir, "notion_pending.json")
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_data = {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "scraper_stats": {},
            "jobs": [],
            "errors": [],
            "_total_added": 0,
            "_analyzed_count": 0,
            "_analyzed_by_gemini": 0,
        }
        self._db = Database()
        self._migrate_if_needed()

    def record_scraper_result(self, name: str, jobs: List[Dict], failed: bool = False, error_msg: str = ""):
        self.run_data["scraper_stats"][name] = {
            "found": len(jobs),
            "failed": failed,
            "error": error_msg,
        }
        for job in jobs:
            job["_scraper"] = name
        self.run_data["jobs"].extend(jobs)
        if failed and error_msg:
            self.run_data["errors"].append(f"[{name}] {error_msg}")

    def record_error(self, msg: str):
        self.run_data["errors"].append(msg)

    def get_scraper_stats(self) -> Dict[str, Dict[str, Any]]:
        return self.run_data["scraper_stats"]

    def get_top_jobs(self, n: int = 10) -> List[Dict]:
        scored = [j for j in self.run_data["jobs"] if j.get("match_score")]
        scored.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return scored[:n]

    def get_total_added(self) -> int:
        return self.run_data.get("_total_added", 0)

    def set_total_added(self, count: int):
        self.run_data["_total_added"] = count

    def set_analyzed_count(self, count: int):
        self.run_data["_analyzed_count"] = count

    def set_analyzed_by_gemini(self, count: int):
        self.run_data["_analyzed_by_gemini"] = count

    def record_enriched_job(self, job: dict):
        enriched_fields = [
            "match_score", "tech_stack", "work_mode", "tailored_advice",
            "salary", "salary_is_estimate", "required_experience",
            "cover_letter", "cv_summary", "cv_experience_adapted",
            "cv_skills", "cv_projects", "custom_cv_url", "custom_cv_html",
            "cover_letter_pdf_url", "interview_prep", "company_profile",
            "project_match", "language", "status",
        ]
        link = job.get("link", "")
        for existing_job in self.run_data["jobs"]:
            if existing_job.get("link") == link:
                for key in enriched_fields:
                    if key in job and job[key] is not None:
                        existing_job[key] = job[key]
                return
        self.run_data["jobs"].append(job)

    def save(self) -> str:
        self._db.create_run(self.run_data)
        links = []
        for job in self.run_data["jobs"]:
            self._db.upsert_job(job)
            link = job.get("link", "")
            if link:
                links.append(link)
        if links:
            self._db.add_run_jobs(self.run_id, links)
        self._db.export_data_json()
        run_count = len(self._db.get_all_runs())
        print(f"[Results] Guardado en BD ({run_count} ejecuciones)")
        return str(self._db.db_path)

    def _load_data(self) -> dict:
        runs_data = self._db.get_all_runs()
        if not runs_data:
            return {"runs": []}

        runs = []
        for run in runs_data:
            run_id = run["run_id"]
            job_ids = self._db.get_run_job_ids(run_id)
            jobs = []
            for jid in job_ids:
                job = self._db.get_job_by_id(jid)
                if job:
                    jobs.append(job)
            run["jobs"] = jobs
            runs.append(run)
        return {"runs": runs}

    def load_all_runs(self) -> List[Dict]:
        data = self._load_data()
        return data.get("runs", [])

    def load_latest_run(self) -> dict:
        latest = self._db.get_latest_run()
        if not latest:
            return {}
        job_ids = self._db.get_run_job_ids(latest["run_id"])
        jobs = []
        for jid in job_ids:
            job = self._db.get_job_by_id(jid)
            if job:
                jobs.append(job)
        latest["jobs"] = jobs
        return latest

    def get_history(self) -> List[Dict]:
        runs = self._db.get_all_runs()
        history = []
        for run in runs:
            stats = run.get("scraper_stats", {})
            history.append({
                "run_id": run.get("run_id", ""),
                "timestamp": run.get("timestamp", ""),
                "total_jobs_found": sum(s.get("found", 0) for s in stats.values()),
                "jobs_added_notion": run.get("_total_added", 0),
                "jobs_analyzed": run.get("_analyzed_count", 0),
                "scrapers_ok": sum(1 for s in stats.values() if not s.get("failed")),
                "scrapers_failed": sum(1 for s in stats.values() if s.get("failed")),
                "errors": len(run.get("errors", [])),
            })
        return history

    def _migrate_if_needed(self):
        if self._db.get_job_count() > 0:
            return
        if os.path.exists(self.data_path_legacy):
            try:
                result = self._db.migrate_from_json(self.data_path_legacy)
                if result["jobs"] > 0:
                    print(f"[Migracion] {result['jobs']} ofertas y {result['runs']} ejecuciones migradas de data.json a SQLite")
            except Exception as e:
                print(f"[Migracion] Error migrando data.json: {e}")

    def add_pending_notion_write(self, job: dict):
        pending = self._load_pending()
        link = job.get("link", "")
        existing_links = {j.get("link") for j in pending}
        if link and link not in existing_links:
            pending.append(job)
            with open(self.pending_path, "w", encoding="utf-8") as f:
                json.dump(pending, f, ensure_ascii=False, indent=2)

    def get_pending_notion_writes(self) -> List[dict]:
        return self._load_pending()

    def clear_pending_notion_write(self, link: str):
        pending = self._load_pending()
        pending = [j for j in pending if j.get("link") != link]
        with open(self.pending_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)

    def _load_pending(self) -> list:
        if os.path.exists(self.pending_path):
            try:
                with open(self.pending_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, KeyError):
                pass
        return []
