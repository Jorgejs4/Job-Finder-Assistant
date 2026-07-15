import json
import csv
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict


class ResultsManager:
    """
    Guarda resultados de cada ejecución en JSON + CSV.
    Registra métricas por plataforma y detecta scrapers caídos.
    """
    def __init__(self, results_dir: str = None):
        if results_dir is None:
            results_dir = os.path.join(Path(__file__).resolve().parent.parent, "results")
        self.results_dir = results_dir
        os.makedirs(self.results_dir, exist_ok=True)
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_data = {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "scraper_stats": {},
            "jobs": [],
            "errors": [],
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

    def save(self) -> str:
        json_path = os.path.join(self.results_dir, f"run_{self.run_id}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.run_data, f, ensure_ascii=False, indent=2)

        csv_path = os.path.join(self.results_dir, f"run_{self.run_id}.csv")
        if self.run_data["jobs"]:
            fieldnames = ["title", "company", "location", "link", "source", "date_posted",
                          "match_score", "work_mode", "salary", "description"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for job in self.run_data["jobs"]:
                    writer.writerow({k: job.get(k, "") for k in fieldnames})

        self._append_history()

        print(f"[Results] Guardados: {json_path}")
        print(f"[Results] Guardados: {csv_path}")
        return json_path

    def _append_history(self):
        history_path = os.path.join(self.results_dir, "history.csv")
        write_header = not os.path.exists(history_path)

        stats = self.run_data["scraper_stats"]
        row = {
            "run_id": self.run_id,
            "timestamp": self.run_data["timestamp"],
            "total_jobs_found": sum(s["found"] for s in stats.values()),
            "jobs_added_notion": self.run_data.get("_total_added", 0),
            "jobs_analyzed": self.run_data.get("_analyzed_count", 0),
            "scrapers_ok": sum(1 for s in stats.values() if not s["failed"]),
            "scrapers_failed": sum(1 for s in stats.values() if s["failed"]),
            "errors": len(self.run_data["errors"]),
        }
        for name, s in stats.items():
            row[f"_{name}_found"] = s["found"]
            row[f"_{name}_ok"] = 0 if s["failed"] else 1

        with open(history_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def load_history(self) -> List[Dict]:
        history_path = os.path.join(self.results_dir, "history.csv")
        if not os.path.exists(history_path):
            return []
        with open(history_path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def load_all_runs(self) -> List[Dict]:
        runs = []
        for p in sorted(Path(self.results_dir).glob("run_*.json"), reverse=True):
            with open(p, "r", encoding="utf-8") as f:
                runs.append(json.load(f))
        return runs
