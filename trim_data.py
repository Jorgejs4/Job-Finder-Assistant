#!/usr/bin/env python3
"""
Compacta data.json: deduplica jobs por URL y mergea todas las ejecuciones en una sola.
Reduce drasticamente el tamano del archivo y acelera el dashboard.

Uso:
    python trim_data.py              # Ejecuta la limpieza
    python trim_data.py --dry-run    # Muestra estadisticas sin guardar
"""
import json
import sys
import os
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "results" / "data.json"


def main():
    dry_run = "--dry-run" in sys.argv

    if not DATA_PATH.exists():
        print("No existe results/data.json")
        return

    before_size = DATA_PATH.stat().st_size
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    runs = data.get("runs", [])
    total_raw = sum(len(r.get("jobs", [])) for r in runs)
    print(f"Antes: {len(runs)} runs, {total_raw} jobs raw, {before_size / 1024 / 1024:.1f} MB")

    jobs_by_url = {}
    for run in runs:
        run_id = run.get("run_id", "")
        run_ts = run.get("timestamp", "")
        for job in run.get("jobs", []):
            url = job.get("link", "")
            if not url:
                continue
            if url in jobs_by_url:
                existing = jobs_by_url[url]
                if run_ts > existing.get("_last_seen", ""):
                    existing["_last_seen"] = run_ts
                    existing["_last_run_id"] = run_id
                if run_ts < existing.get("_first_seen", ""):
                    existing["_first_seen"] = run_ts
                for key in ["cover_letter", "custom_cv_url", "custom_cv_html",
                            "cover_letter_pdf_url", "language", "interview_prep",
                            "match_score", "tech_stack", "tailored_advice",
                            "salary", "work_mode", "salary_is_estimate",
                            "required_experience", "status",
                            "company_profile", "project_match"]:
                    if job.get(key):
                        existing[key] = job[key]
            else:
                job["_first_seen"] = run_ts
                job["_last_seen"] = run_ts
                job["_last_run_id"] = run_id
                jobs_by_url[url] = job

    unique_jobs = list(jobs_by_url.values())
    print(f"Despues: 1 run, {len(unique_jobs)} jobs unicos")

    trimmed = {
        "runs": [{
            "run_id": "trimmed",
            "timestamp": runs[0].get("timestamp", "") if runs else "",
            "jobs": unique_jobs,
            "scraper_stats": {},
        }]
    }

    if dry_run:
        out_size = len(json.dumps(trimmed, ensure_ascii=False).encode("utf-8"))
        print(f"Tamano resultante: {out_size / 1024 / 1024:.1f} MB (ahorro: {(1 - out_size / before_size) * 100:.0f}%)")
        print("DRY RUN - no se guardo nada.")
    else:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
        after_size = DATA_PATH.stat().st_size
        print(f"Guardado: {after_size / 1024 / 1024:.1f} MB (ahorro: {(1 - after_size / before_size) * 100:.0f}%)")


if __name__ == "__main__":
    main()
