#!/usr/bin/env python3
"""
Analiza con Gemini las ofertas que nunca fueron procesadas (match_score ausente).
Lee data.json, encuentra ofertas sin analizar, llama a Gemini y guarda los resultados.
Progreso se guarda cada 10 ofertas para no perder trabajo.

Uso:
    python analyze_pending.py             # Analiza todas las pendientes
    python analyze_pending.py --limit 50  # Analiza solo 50
    python analyze_pending.py --dry-run   # Muestra cuántas sin procesar
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from utils.gemini_client import GeminiClient, KeyPool
from utils.cv_parser import parse_cv
from utils.cv_generator import CVGenerator


DATA_PATH = Path(__file__).resolve().parent / "results" / "data.json"
SAVE_INTERVAL = 10


class RateLimiter:
    def __init__(self, min_interval=10.0):
        self._min_interval = min_interval
        self._interval = min_interval
        self._last_call = 0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_call = time.time()

    def reset_interval(self):
        with self._lock:
            self._interval = self._min_interval

    def backoff(self):
        with self._lock:
            self._interval = min(self._interval * 4, 120)
            print(f"\n[RateLimit] Backoff → intervalo {self._interval}s")


def load_data():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"runs": []}


def save_data(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[Save] Guardado en {DATA_PATH}")


def aggregate_all_jobs(data):
    """Devuelve dict url → job con merge de todas las ejecuciones."""
    jobs_by_url = {}
    for run in data.get("runs", []):
        for job in run.get("jobs", []):
            url = job.get("link", "")
            if not url:
                continue
            if url not in jobs_by_url:
                jobs_by_url[url] = job
            else:
                existing = jobs_by_url[url]
                for key in ["cover_letter", "custom_cv_url", "custom_cv_html",
                            "match_score", "tech_stack", "tailored_advice",
                            "salary", "work_mode", "salary_is_estimate",
                            "required_experience", "status"]:
                    if job.get(key):
                        existing[key] = job[key]
    return jobs_by_url


def write_job_back(data, url, updated_job):
    """Escribe el job actualizado de vuelta en todas las ejecuciones que lo contienen."""
    for run in data.get("runs", []):
        for i, job in enumerate(run.get("jobs", [])):
            if job.get("link") == url:
                run["jobs"][i].update(updated_job)
                return


def analyze_single(gemini, cv_text, job, rate_limiter):
    """Analiza un job con Gemini. Devuelve dict con los campos actualizados."""
    rate_limiter.wait()
    desc = job.get("description") or job.get("title", "")
    experience_hint = job.get("experience_hint", 0)

    match_result = gemini.match_offer(
        cv_text=cv_text,
        offer_title=job["title"],
        offer_description=desc,
        experience_hint=experience_hint,
    )
    rate_limiter.reset_interval()

    updates = {
        "match_score": match_result.match_score,
        "tech_stack": match_result.tech_stack,
        "tailored_advice": match_result.tailored_advice,
        "salary": str(match_result.estimated_salary),
        "work_mode": match_result.work_mode,
        "salary_is_estimate": match_result.salary_is_estimate,
        "required_experience": match_result.required_experience,
    }
    if match_result.cover_letter:
        updates["cover_letter"] = match_result.cover_letter

    return updates


def main():
    parser = argparse.ArgumentParser(description="Analizar ofertas pendientes con Gemini")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de ofertas a analizar (0=todas)")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar estadísticas")
    parser.add_argument("--cv", type=str, default=None, help="Ruta al CV (default: config.CV_PATH)")
    parser.add_argument("--workers", type=int, default=1, help="Número de hilos Gemini (default: 1)")
    args = parser.parse_args()

    config.validate_config()
    config.load_preferences()

    cv_path = args.cv or config.CV_PATH
    print(f"[CV] Leyendo: {cv_path}")
    cv_text = parse_cv(cv_path)
    print(f"[CV] OK. {len(cv_text)} caracteres")

    data = load_data()
    jobs_by_url = aggregate_all_jobs(data)
    all_jobs = list(jobs_by_url.values())

    unanalyzed = [(url, j) for url, j in jobs_by_url.items() if not j.get("match_score")]
    print(f"\n[Estadísticas]")
    print(f"  Total ofertas: {len(all_jobs)}")
    print(f"  Analizadas: {len(all_jobs) - len(unanalyzed)}")
    print(f"  Pendientes: {len(unanalyzed)}")

    if args.dry_run:
        return

    limit = args.limit if args.limit > 0 else len(unanalyzed)
    to_analyze = unanalyzed[:limit]
    print(f"\n[Va a analizar] {len(to_analyze)} ofertas con {args.workers} hilo(s)")

    gemini = GeminiClient()
    rate_limiter = RateLimiter(min_interval=10.0)
    cv_gen = CVGenerator()

    analyzed = 0
    failed = 0
    saved = 0
    stop_event = threading.Event()

    t0 = time.time()

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for url, job in to_analyze:
                if stop_event.is_set():
                    break
                future = executor.submit(analyze_single, gemini, cv_text, job, rate_limiter)
                futures[future] = (url, job)

            for future in as_completed(futures):
                if stop_event.is_set():
                    break
                url, job = futures[future]
                try:
                    updates = future.result()
                    job.update(updates)
                    write_job_back(data, url, updates)
                    analyzed += 1

                    match = updates.get("match_score", 0)
                    print(f"  [{analyzed}/{len(to_analyze)}] {job['title'][:40]} @ {job.get('company', '')[:20]} — match {match}%", flush=True)

                    # Generar CV para ofertas con match >= 50
                    if match >= 50:
                        try:
                            job_data = {
                                "title": job["title"],
                                "company": job.get("company", ""),
                                "tech_stack": job.get("tech_stack", []),
                                "tailored_advice": updates.get("tailored_advice", ""),
                            }
                            html_path, pdf_path = cv_gen.generate(
                                gemini, cv_text, job_data, cv_pdf_path=cv_path
                            )
                            if pdf_path:
                                slug = os.path.basename(pdf_path)
                                job["custom_cv_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                            if html_path:
                                job["custom_cv_html"] = os.path.basename(html_path)
                            write_job_back(data, url, job)
                        except Exception as e:
                            print(f"    [CV Error] {e}")

                except RuntimeError as e:
                    if "429" in str(e):
                        print(f"\n[CRÍTICO] Todas las API keys agotadas. Parando.")
                        stop_event.set()
                        break
                    failed += 1
                    print(f"  [Error] {job.get('title', '?')}: {e}")
                except Exception as e:
                    failed += 1
                    print(f"  [Error] {job.get('title', '?')}: {e}")

                if (analyzed + failed) % SAVE_INTERVAL == 0:
                    save_data(data)
                    saved = analyzed + failed
    else:
        for url, job in to_analyze:
            if stop_event.is_set():
                break
            try:
                updates = analyze_single(gemini, cv_text, job, rate_limiter)
                job.update(updates)
                write_job_back(data, url, updates)
                analyzed += 1

                match = updates.get("match_score", 0)
                print(f"  [{analyzed}/{len(to_analyze)}] {job['title'][:40]} @ {job.get('company', '')[:20]} — match {match}%", flush=True)

                if match >= 50:
                    try:
                        job_data = {
                            "title": job["title"],
                            "company": job.get("company", ""),
                            "tech_stack": job.get("tech_stack", []),
                            "tailored_advice": updates.get("tailored_advice", ""),
                        }
                        html_path, pdf_path = cv_gen.generate(
                            gemini, cv_text, job_data, cv_pdf_path=cv_path
                        )
                        if pdf_path:
                            slug = os.path.basename(pdf_path)
                            job["custom_cv_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                        if html_path:
                            job["custom_cv_html"] = os.path.basename(html_path)
                        write_job_back(data, url, job)
                    except Exception as e:
                        print(f"    [CV Error] {e}")

            except RuntimeError as e:
                if "429" in str(e):
                    print(f"\n[CRÍTICO] Todas las API keys agotadas. Parando.")
                    stop_event.set()
                    break
                failed += 1
                print(f"  [Error] {job.get('title', '?')}: {e}")
            except Exception as e:
                failed += 1
                print(f"  [Error] {job.get('title', '?')}: {e}")

            if (analyzed + failed) % SAVE_INTERVAL == 0:
                save_data(data)
                saved = analyzed + failed

    # Guardar progreso final
    if (analyzed + failed) > saved:
        save_data(data)

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"  ANÁLISIS COMPLETADO")
    print(f"{'=' * 60}")
    print(f"  Analizadas: {analyzed}")
    print(f"  Fallidas: {failed}")
    print(f"  Tiempo: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  API keys usadas: {gemini.key_pool.active_index + 1}/{gemini.key_pool.total_keys}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
