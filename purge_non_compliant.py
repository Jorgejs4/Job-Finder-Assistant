#!/usr/bin/env python3
"""
Purga ofertas que no cumplen modalidad+ubicación.
- Remoto: siempre se mantiene
- Híbrido / Presencial: solo se mantienen si la ubicación contiene USER_CITY
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DATA_FILE = RESULTS_DIR / "data.json"


def is_remote(job):
    wm = config.normalize_work_mode(job.get("work_mode", ""))
    return wm == "Remoto"


def matches_city(job, city):
    loc = job.get("location", "").lower()
    return city in loc


def main():
    config.load_preferences()
    city = config.USER_CITY
    print(f"[Purga] Ciudad objetivo: {city}")

    if not DATA_FILE.exists():
        print("[Purga] No existe data.json")
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    archived_count = 0
    kept_count = 0
    already_archived = 0

    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            if job.get("archived"):
                already_archived += 1
                continue

            wm = config.normalize_work_mode(job.get("work_mode", ""))

            if wm == "Remoto":
                kept_count += 1
                continue

            if wm in ("Híbrido", "Presencial"):
                if matches_city(job, city):
                    kept_count += 1
                else:
                    job["archived"] = True
                    archived_count += 1
            else:
                kept_count += 1

    if archived_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Purga] {archived_count} ofertas archivadas (Híbrido/Presencial fuera de {city})")
    else:
        print("[Purga] No hay ofertas para archivar")

    print(f"[Purga] Resumen: {kept_count} mantenidas, {archived_count} archivadas, {already_archived} ya archivadas")


if __name__ == "__main__":
    main()
