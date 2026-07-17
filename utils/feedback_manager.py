import json
import os
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional


class FeedbackManager:
    """
    Gestiona feedback de usuarios sobre CVs generados.
    Almacena en results/feedback.json y permite regeneración en la próxima ejecución.
    """
    def __init__(self, results_dir: str = None):
        if results_dir is None:
            results_dir = os.path.join(Path(__file__).resolve().parent.parent, "results")
        self.results_dir = results_dir
        self.feedback_path = os.path.join(results_dir, "feedback.json")
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.feedback_path):
            try:
                with open(self.feedback_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, KeyError):
                pass
        return {"pending": [], "completed": []}

    def _save(self):
        os.makedirs(self.results_dir, exist_ok=True)
        with open(self.feedback_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def make_job_id(title: str, company: str) -> str:
        return hashlib.md5(f"{title}-{company}".encode()).hexdigest()[:12]

    def save_feedback(self, title: str, company: str, feedback_text: str) -> str:
        """Guarda feedback pendiente. Devuelve job_id."""
        job_id = self.make_job_id(title, company)

        # Eliminar si ya existía en pending (reemplazar)
        self._data["pending"] = [
            p for p in self._data["pending"] if p.get("job_id") != job_id
        ]

        entry = {
            "job_id": job_id,
            "title": title,
            "company": company,
            "feedback": feedback_text,
        }
        self._data["pending"].append(entry)
        self._save()
        print(f"[Feedback] Guardado feedback para {title} @ {company} (id={job_id})")
        return job_id

    def get_pending(self) -> List[Dict[str, Any]]:
        return list(self._data["pending"])

    def get_pending_for(self, title: str, company: str) -> Optional[Dict[str, Any]]:
        job_id = self.make_job_id(title, company)
        for p in self._data["pending"]:
            if p.get("job_id") == job_id:
                return p
        return None

    def mark_done(self, job_id: str):
        entry = None
        for p in self._data["pending"]:
            if p.get("job_id") == job_id:
                entry = p
                break
        if entry:
            self._data["pending"] = [
                p for p in self._data["pending"] if p.get("job_id") != job_id
            ]
            entry["status"] = "completed"
            self._data["completed"].append(entry)
            self._save()
            print(f"[Feedback] Feedback {job_id} marcado como completado")

    def has_pending(self, title: str, company: str) -> bool:
        return self.get_pending_for(title, company) is not None

    def count_pending(self) -> int:
        return len(self._data["pending"])
