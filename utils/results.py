import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


class ResultsManager:
    """
    Guarda todos los resultados en un único archivo data.json que se acumula.
    Cada ejecución se añade al inicio de la lista (más reciente primero).
    """
    def __init__(self, results_dir: str = None):
        if results_dir is None:
            results_dir = os.path.join(Path(__file__).resolve().parent.parent, "results")
        self.results_dir = results_dir
        os.makedirs(self.results_dir, exist_ok=True)
        self.data_path = os.path.join(self.results_dir, "data.json")
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
        }

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

    def record_enriched_job(self, job: dict):
        """Guarda un job enriquecido (con match_score, tech_stack, etc.) en run_data."""
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
        # Cargar datos existentes
        data = self._load_data()
        
        # Añadir esta ejecución al inicio (más reciente primero)
        data["runs"].insert(0, self.run_data)
        
        # Mantener solo las últimas 100 ejecuciones para no crecer infinitamente
        if len(data["runs"]) > 100:
            data["runs"] = data["runs"][:100]
        
        # Guardar
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        run_count = len(data["runs"])
        print(f"[Results] Guardado en {self.data_path} ({run_count} ejecuciones)")
        return self.data_path

    def _load_data(self) -> dict:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "runs" in data:
                    return data
            except (json.JSONDecodeError, KeyError):
                pass
        return {"runs": []}

    def load_all_runs(self) -> List[Dict]:
        data = self._load_data()
        return data.get("runs", [])

    def load_latest_run(self) -> dict:
        runs = self.load_all_runs()
        return runs[0] if runs else {}

    def get_history(self) -> List[Dict]:
        """Genera historial resumido a partir de data.json"""
        runs = self.load_all_runs()
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

    def add_pending_notion_write(self, job: dict):
        """Guarda un job que falló al escribir en Notion para reintentar después."""
        pending = self._load_pending()
        link = job.get("link", "")
        existing_links = {j.get("link") for j in pending}
        if link and link not in existing_links:
            pending.append(job)
            with open(self.pending_path, "w", encoding="utf-8") as f:
                json.dump(pending, f, ensure_ascii=False, indent=2)

    def get_pending_notion_writes(self) -> List[dict]:
        """Devuelve la lista de jobs pendientes de escribir en Notion."""
        return self._load_pending()

    def clear_pending_notion_write(self, link: str):
        """Elimina un job de la cola de pendientes tras escribir con éxito."""
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
