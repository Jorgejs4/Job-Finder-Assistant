#!/usr/bin/env python3
"""
Re-filtra todas las ofertas en data.json segun los criterios de ubicacion y modalidad.

Regla:
  - Ofertas REMOTO/TELETRABAJO -> siempre se incluyen
  - Ofertas PRESENCIAL/HIBRIDO -> solo si la ubicacion coincide con la ciudad deseada

Las ofertas que no cumplen se marcan como "archived" en data.json (no se borran).

Uso:
    python refilter.py                  # Ejecuta el refiltrado
    python refilter.py --dry-run        # Solo muestra que se archivaria
    python refilter.py --unarchive      # Desarchiva todo (resetea filtros)
"""
import os
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

DATA_PATH = Path(__file__).resolve().parent / "results" / "data.json"


def is_remote(job: dict) -> bool:
    wm = config.reclassify_work_mode(job)
    job["work_mode"] = wm
    return wm == "Remoto"


def matches_location(job: dict, desired_cities: list) -> bool:
    job_loc = job.get("location", "").lower()
    return any(city in job_loc for city in desired_cities)


def classify_archive_reason(job: dict, desired_cities: list) -> str | None:
    from config import classify_archive_reason as _classify
    return _classify(job)


def should_keep(job: dict, desired_cities: list) -> bool:
    return classify_archive_reason(job, desired_cities) is None


def main():
    parser = argparse.ArgumentParser(description="Re-filtrar ofertas por ubicacion y modalidad")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar estadisticas sin modificar")
    parser.add_argument("--unarchive", action="store_true", help="Desarchivar todas las ofertas")
    parser.add_argument("--location", type=str, default=None, help="Ciudad deseada (ej: Sevilla, Madrid, London)")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"[Error] No se encontro {DATA_PATH}")
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
    print(f"[Total] {total} ofertas unicas")

    if args.unarchive:
        count = 0
        for run in data.get("runs", []):
            for job in run.get("jobs", []):
                if job.get("archived"):
                    job["archived"] = False
                    count += 1
        if not args.dry_run and count > 0:
            with open(DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[OK] {count} ofertas desarchivadas")
        return

    if args.location:
        desired_cities = [c.strip().lower() for c in args.location.split(",")]
        print(f"[Ciudad] {desired_cities}")
    else:
        os.environ.setdefault("DESIRED_LOCATIONS", "Remoto")
        config.load_preferences()
        desired_cities = [loc for loc in config.DESIRED_LOCATIONS if loc not in ["remoto", "remote"]]
        print(f"[Ciudad] {desired_cities}")

    kept = 0
    to_archive = 0
    already_archived = 0
    newly_archived = 0
    examples = []

    # Decidir por URL deduplicada, luego aplicar a TODAS las copias
    archive_urls = set()
    keep_urls = set()
    for url, job in all_jobs.items():
        if job.get("archived"):
            already_archived += 1
            continue
        # Reclasificar work_mode antes de filtrar
        job["work_mode"] = config.reclassify_work_mode(job)
        reason = classify_archive_reason(job, desired_cities)
        if reason is None:
            kept += 1
            keep_urls.add(url)
        else:
            to_archive += 1
            archive_urls.add((url, reason))
            if len(examples) < 10:
                examples.append(job)

    # Aplicar decided a TODAS las copias en TODOS los runs
    if archive_urls:
        archive_map = {url: reason for url, reason in archive_urls}
        for run in data.get("runs", []):
            for job in run.get("jobs", []):
                url = job.get("link", "")
                if url in archive_map and not job.get("archived"):
                    job["archived"] = True
                    job["archive_reason"] = archive_map[url]
                    newly_archived += 1
    # Also unarchive URLs that should be kept
    if keep_urls:
        for run in data.get("runs", []):
            for job in run.get("jobs", []):
                url = job.get("link", "")
                if url in keep_urls and job.get("archived"):
                    job["archived"] = False
                    job.pop("archive_reason", None)

    print(f"  OK se mantienen: {kept}")
    print(f"  Ya archivadas: {already_archived}")
    print(f"  Nuevas a archivar: {newly_archived}")

    if examples:
        print(f"\n[Ejemplo] Primeras 10 ofertas a archivar:")
        for i, job in enumerate(examples):
            wm = job.get("work_mode", "?")
            loc = job.get("location", "?")
            print(f"  {i+1}. [{wm}] {job.get('title', '?')[:50]} @ {job.get('company', '?')} -- {loc}")

    if args.dry_run:
        print("\n[Dry Run] No se realizaron cambios.")
        return

    if newly_archived > 0:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] data.json actualizado. {newly_archived} ofertas archivadas.")
    else:
        print(f"\n[OK] Nada que archivar.")


if __name__ == "__main__":
    main()
