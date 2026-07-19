#!/usr/bin/env python3
"""
Re-filtra todas las ofertas en data.json según los criterios de ubicación y modalidad.

Regla:
  - Ofertas REMOTO/TELETRABAJO → siempre se incluyen
  - Ofertas PRESENCIAL/HÍBRIDO → solo si la ubicación coincide con DESIRED_LOCATIONS

Uso:
    python refilter.py                  # Ejecuta el refiltrado
    python refilter.py --dry-run        # Solo muestra qué se eliminaría
    python refilter.py --archive        # Mueve eliminadas a data_filtered.json
"""
import os
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

DATA_PATH = Path(__file__).resolve().parent / "results" / "data.json"
ARCHIVE_PATH = Path(__file__).resolve().parent / "results" / "data_filtered.json"


def is_remote(job: dict) -> bool:
    """Detecta si una oferta es remota/teletrabajo."""
    wm = str(job.get("work_mode", "")).lower()
    if "remot" in wm or "teletrabaj" in wm or "distancia" in wm or "home office" in wm:
        return True
    text = f"{job.get('title', '')} {job.get('description', '')} {job.get('location', '')}".lower()
    remote_kw = ["remoto", "remote", "teletrabajo", "distancia", "virtual", "home office"]
    return any(kw in text for kw in remote_kw)


def matches_location(job: dict, desired_cities: list) -> bool:
    """Verifica si la ubicación de la oferta coincide con alguna ciudad deseada."""
    job_loc = job.get("location", "").lower()
    return any(city in job_loc for city in desired_cities)


def should_keep(job: dict, desired_cities: list) -> bool:
    """Determina si una oferta debe conservarse."""
    if is_remote(job):
        return True
    return matches_location(job, desired_cities)


def main():
    parser = argparse.ArgumentParser(description="Re-filtrar ofertas por ubicación y modalidad")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar estadísticas sin modificar")
    parser.add_argument("--archive", action="store_true", help="Mover ofertas eliminadas a data_filtered.json")
    args = parser.parse_args()

    config.load_preferences()
    desired_cities = [loc for loc in config.DESIRED_LOCATIONS if loc not in ["remoto", "remote"]]
    print(f"[Config] Ciudades deseadas: {desired_cities}")
    print(f"[Config] Ubicaciones completas: {config.DESIRED_LOCATIONS}")

    if not DATA_PATH.exists():
        print(f"[Error] No se encontró {DATA_PATH}")
        sys.exit(1)

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_jobs = {}
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            url = job.get("link", "")
            if not url:
                continue
            if url not in all_jobs:
                all_jobs[url] = job

    total = len(all_jobs)
    print(f"\n[Estadísticas] Total ofertas únicas: {total}")

    kept = {}
    removed = {}
    for url, job in all_jobs.items():
        if should_keep(job, desired_cities):
            kept[url] = job
        else:
            removed[url] = job

    print(f"  [OK] Se mantienen: {len(kept)}")
    print(f"  [X] Se eliminan: {len(removed)}")

    if removed:
        print(f"\n[Ejemplo] Primeras 10 ofertas eliminadas:")
        for i, (url, job) in enumerate(list(removed.items())[:10]):
            wm = job.get("work_mode", "?")
            loc = job.get("location", "?")
            print(f"  {i+1}. [{wm}] {job.get('title', '?')[:50]} @ {job.get('company', '?')} -- {loc}")

    if args.dry_run:
        print("\n[Dry Run] No se realizaron cambios.")
        return

    if args.archive and removed:
        archive = {}
        if ARCHIVE_PATH.exists():
            with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
                archive = json.load(f)
        archive.setdefault("filtered_jobs", [])
        existing_urls = {j.get("link") for j in archive["filtered_jobs"]}
        for url, job in removed.items():
            if url not in existing_urls:
                archive["filtered_jobs"].append(job)
        with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        print(f"[Archive] {len(removed)} ofertas guardadas en {ARCHIVE_PATH}")

    for run in data.get("runs", []):
        run["jobs"] = [j for j in run.get("jobs", []) if j.get("link", "") in kept]

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] data.json actualizado. {len(kept)} ofertas restantes.")


if __name__ == "__main__":
    main()
