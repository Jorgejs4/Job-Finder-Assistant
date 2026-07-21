#!/usr/bin/env python3
"""
Reclasifica work_mode de TODAS las ofertas usando reglas de texto,
luego aplica el filtro de ubicación/modalidad.

Pasos:
  1. Desarchivar todo
  2. Reclasificar work_mode con reclassify_work_mode()
  3. Aplicar filtro: Remoto -> queda, Híbrido/Presencial -> solo si ciudad coincide
  4. Guardar

Uso:
    python reclassify_all.py                  # Ejecuta todo
    python reclassify_all.py --dry-run        # Solo muestra estadísticas
    python reclassify_all.py --city sevilla   # Ciudad objetivo (default: config.USER_CITY)
"""
import os
import sys
import json
import argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

DATA_PATH = Path(__file__).resolve().parent / "results" / "data.json"


def main():
    parser = argparse.ArgumentParser(description="Reclasificar y refiltrar todas las ofertas")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar estadísticas")
    parser.add_argument("--city", type=str, default=None, help="Ciudad objetivo")
    args = parser.parse_args()

    config.load_preferences()
    city = (args.city or config.USER_CITY).lower()
    print(f"[Config] Ciudad objetivo: {city}")

    if not DATA_PATH.exists():
        print(f"[Error] No se encontro {DATA_PATH}")
        sys.exit(1)

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Recolectar ofertas únicas por URL
    seen_urls = set()
    jobs_list = []
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            url = job.get("link", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                jobs_list.append(job)

    total = len(jobs_list)
    print(f"[Total] {total} ofertas únicas")

    # 2. Desarchivar todo
    unarchived = 0
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            if job.get("archived"):
                job["archived"] = False
                unarchived += 1
    print(f"[Unarchive] {unarchived} ofertas desarchivadas")

    # 3. Reclasificar work_mode
    mode_before = Counter()
    mode_after = Counter()
    changed = 0

    for job in jobs_list:
        old_wm = job.get("work_mode", "")
        mode_before[old_wm] += 1

        new_wm = config.reclassify_work_mode(job)
        job["work_mode"] = new_wm
        mode_after[new_wm] += 1

        if old_wm != new_wm:
            changed += 1

    print(f"\n[Reclassify] {changed} ofertas reclasificadas")
    print(f"\n  Antes:")
    for wm, c in mode_before.most_common():
        label = wm if wm else "(vacío)"
        print(f"    {label}: {c}")
    print(f"\n  Después:")
    for wm, c in mode_after.most_common():
        print(f"    {wm}: {c}")

    # 4. Aplicar filtro de ubicación
    kept = 0
    archived_count = 0
    archive_examples = []

    for job in jobs_list:
        match = job.get("match_score", 0) or 0
        if match < 10:
            job["archived"] = True
            archived_count += 1
            if len(archive_examples) < 15:
                archive_examples.append(job)
            continue
        wm = job.get("work_mode", "")
        if wm == "Remoto":
            kept += 1
            continue
        loc = (job.get("location", "") or "").lower()
        if city in loc:
            kept += 1
        else:
            job["archived"] = True
            archived_count += 1
            if len(archive_examples) < 15:
                archive_examples.append(job)

    print(f"\n[Filtro] {kept} ofertas se quedan, {archived_count} se archivan")

    if archive_examples:
        print(f"\n[Ejemplos] Primeras 15 ofertas a archivar:")
        for i, j in enumerate(archive_examples):
            wm = j.get("work_mode", "?")
            loc = j.get("location", "?")
            print(f"  {i+1}. [{wm}] {j.get('title', '?')[:50]} @ {j.get('company', '?')} — {loc}")

    # 5. Resumen por work_mode de las archivadas
    archive_modes = Counter()
    for job in jobs_list:
        if job.get("archived"):
            archive_modes[job.get("work_mode", "?")] += 1
    if archive_modes:
        print(f"\n[Resumen archivadas por modalidad]:")
        for wm, c in archive_modes.most_common():
            print(f"  {wm}: {c}")

    if args.dry_run:
        print("\n[Dry Run] No se realizaron cambios.")
        return

    # 6. Guardar
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] data.json guardado. {kept} mantenidas, {archived_count} archivadas.")


if __name__ == "__main__":
    main()
