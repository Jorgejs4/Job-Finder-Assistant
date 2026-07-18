#!/usr/bin/env python3
"""
Tests automatizados para todos los scrapers.
Detecta cuándo un scraper se rompe (cambios en HTML, bloqueos, APIs caídas).
Se puede ejecutar en GitHub Actions en cada push o como cron job.
"""
import os
import sys
import json
import time
import traceback
from datetime import datetime
from pathlib import Path

os.environ.setdefault("DESIRED_LOCATIONS", "Remoto")
os.environ.setdefault("MOCK_GEMINI", "true")
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("GEMINI_API_KEYS", "test-key-not-real")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
config.load_preferences()

TEST_QUERY = "developer"
TEST_LOCATIONS = config.DESIRED_LOCATIONS

results = {}
errors = []

ALL_SCRAPERS = {
    "InfoJobs": ("scrapers.infojobs_scraper", "InfoJobsScraper"),
    "LinkedIn": ("scrapers.linkedin_scraper", "LinkedInScraper"),
    "Indeed": ("scrapers.indeed_scraper", "IndeedScraper"),
    "RemoteOK": ("scrapers.remoteok_scraper", "RemoteOKScraper"),
    "Remotive": ("scrapers.remotive_scraper", "RemotiveScraper"),
    "TecnoJobs": ("scrapers.tecnobs_scraper", "TecnoJobsScraper"),
    "Jobfluent": ("scrapers.jobfluent_scraper", "JobfluentScraper"),
    "Jooble": ("scrapers.jooble_scraper", "JoobleScraper"),
    "GetOnBoard": ("scrapers.getonbrd_scraper", "GetOnBoardScraper"),
}

MAX_PER_PLATFORM = 50


def import_scraper(module_path: str, class_name: str):
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


def test_scraper(name: str, module_path: str, class_name: str):
    start = time.time()
    try:
        scraper = import_scraper(module_path, class_name)
        jobs = scraper.scrape_jobs(TEST_QUERY, TEST_LOCATIONS)
        elapsed = round(time.time() - start, 2)

        over_limit = len(jobs) > MAX_PER_PLATFORM
        if over_limit:
            jobs = jobs[:MAX_PER_PLATFORM]
            print(f"  [WARN] Recortado de más de {MAX_PER_PLATFORM} a {MAX_PER_PLATFORM}")

        job_links = [j.get("link", "") for j in jobs if j.get("link")]
        unique_links = set(job_links)
        duplicates = len(job_links) - len(unique_links)

        result = {
            "status": "OK",
            "jobs_found": len(jobs),
            "unique_links": len(unique_links),
            "duplicates": duplicates,
            "elapsed_seconds": elapsed,
            "sample_title": jobs[0].get("title", "") if jobs else "",
            "sample_company": jobs[0].get("company", "") if jobs else "",
        }

        if not jobs:
            result["status"] = "EMPTY"
            print(f"  [{name}] WARN: Sin resultados ({elapsed}s)")
        else:
            print(f"  [{name}] OK: {len(jobs)} ofertas ({elapsed}s)")
            print(f"    Muestra: {result['sample_title']} @ {result['sample_company']}")

        return result

    except Exception as e:
        elapsed = round(time.time() - start, 2)
        error_msg = f"{type(e).__name__}: {e}"
        print(f"  [{name}] FALLO: {error_msg} ({elapsed}s)")
        traceback.print_exc()
        return {
            "status": "FAILED",
            "jobs_found": 0,
            "error": error_msg,
            "elapsed_seconds": elapsed,
        }


def main():
    print("=" * 60)
    print("  TESTS AUTOMATIZADOS DE SCRAPERS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Query: '{TEST_QUERY}' | Locations: {TEST_LOCATIONS}")
    print("=" * 60)

    for name, (mod, cls) in ALL_SCRAPERS.items():
        print(f"\n--- Probando {name} ---")
        result = test_scraper(name, mod, cls)
        results[name] = result
        time.sleep(1)

    print("\n" + "=" * 60)
    print("  RESUMEN")
    print("=" * 60)

    ok_count = sum(1 for r in results.values() if r["status"] == "OK")
    empty_count = sum(1 for r in results.values() if r["status"] == "EMPTY")
    failed_count = sum(1 for r in results.values() if r["status"] == "FAILED")
    total_jobs = sum(r.get("jobs_found", 0) for r in results.values())

    print(f"  OK: {ok_count} | Vacíos: {empty_count} | Fallidos: {failed_count}")
    print(f"  Total ofertas: {total_jobs}")
    print()

    for name, r in results.items():
        status = r["status"]
        icon = "✓" if status == "OK" else "~" if status == "EMPTY" else "✗"
        found = r.get("jobs_found", 0)
        elapsed = r.get("elapsed_seconds", 0)
        extra = ""
        if status == "FAILED":
            extra = f" — {r.get('error', '')}"
        print(f"  {icon} {name:25s} | {found:3d} ofertas | {elapsed:5.1f}s{extra}")

    report_path = Path(__file__).resolve().parent.parent / "results" / "test_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "query": TEST_QUERY,
            "locations": TEST_LOCATIONS,
            "summary": {
                "ok": ok_count,
                "empty": empty_count,
                "failed": failed_count,
                "total_jobs": total_jobs,
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[Report] Guardado en {report_path}")

    if failed_count > 0:
        print(f"\n⚠ {failed_count} scraper(s) FALLARON")
        sys.exit(1)
    else:
        print("\n✓ Todos los scrapers responden correctamente")
        sys.exit(0)


if __name__ == "__main__":
    main()
