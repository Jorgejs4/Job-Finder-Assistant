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
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from utils.gemini_client import GeminiClient, KeyPool
from utils.cv_parser import parse_cv
from utils.cv_generator import CVGenerator
from notion_sync import NotionSync


DATA_PATH = Path(__file__).resolve().parent / "results" / "data.json"
SAVE_INTERVAL = 10


def sync_to_notion(notion, job):
    """Sincroniza un job re-analizado con Notion. Actualiza si existe, crea si no."""
    if not notion:
        return
    url = job.get("link", "")
    if not url:
        return
    try:
        if notion.check_if_job_exists(url):
            notion.update_job_fields(job)
        else:
            notion.add_job_to_notion(job)
    except Exception as e:
        print(f"    [Notion Sync] Error: {e}")


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
                            "cover_letter_pdf_url",
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
    """Analiza un job con Gemini. 3 llamadas separadas: basic, details, cv."""
    if gemini.key_pool.exhausted:
        raise RuntimeError("429 - Todas las API keys de Gemini agotadas.")
    desc = job.get("description") or job.get("title", "")
    experience_hint = job.get("experience_hint", 0)
    language = config.detect_language(job.get("source", ""), job.get("title", ""), desc)

    # Llamada 1: match score + tech_stack + work_mode (3 campos)
    rate_limiter.wait()
    match_result = gemini.match_offer(
        cv_text=cv_text,
        offer_title=job["title"],
        offer_description=desc,
        experience_hint=experience_hint,
        language=language,
    )
    rate_limiter.reset_interval()

    updates = {
        "match_score": match_result.match_score,
        "tech_stack": match_result.tech_stack,
        "work_mode": config.normalize_work_mode(match_result.work_mode),
        "language": language,
    }

    # Llamada 2: salary + experience + advice (4 campos)
    rate_limiter.wait()
    try:
        details = gemini.match_details(
            cv_text=cv_text,
            offer_title=job["title"],
            offer_description=desc,
            match_result=match_result,
            language=language,
        )
        rate_limiter.reset_interval()
        updates["estimated_salary"] = details.estimated_salary
        updates["salary"] = str(details.estimated_salary)
        updates["salary_is_estimate"] = details.salary_is_estimate
        updates["required_experience"] = details.required_experience
        updates["tailored_advice"] = details.tailored_advice
    except Exception as e:
        rate_limiter.backoff()
        print(f"    [Details error] {e}")
        updates["salary"] = "0"
        updates["salary_is_estimate"] = True
        updates["required_experience"] = 0
        updates["tailored_advice"] = "No se pudieron generar consejos."

    # Llamada 3a: cover letter + cv summary
    rate_limiter.wait()
    try:
        cv_text_data = gemini.customize_cv_text(
            cv_text=cv_text,
            offer_title=job["title"],
            offer_description=desc,
            match_result=match_result,
            language=language,
        )
        rate_limiter.reset_interval()
        updates["cover_letter"] = cv_text_data.cover_letter
        updates["cv_summary"] = cv_text_data.cv_summary
    except Exception as e:
        rate_limiter.backoff()
        print(f"    [CV text error] {e}")

    # Llamada 3b: experience + skills + projects
    rate_limiter.wait()
    try:
        cv_exp_data = gemini.customize_cv_data(
            cv_text=cv_text,
            offer_title=job["title"],
            offer_description=desc,
            match_result=match_result,
            language=language,
        )
        rate_limiter.reset_interval()
        updates["cv_experience_adapted"] = cv_exp_data.cv_experience_adapted
        updates["cv_skills"] = cv_exp_data.cv_skills
        updates["cv_projects"] = cv_exp_data.cv_projects
    except Exception as e:
        rate_limiter.backoff()
        print(f"    [CV data error] {e}")

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

    notion = None
    if config.NOTION_TOKEN and config.NOTION_DATABASE_ID:
        try:
            notion = NotionSync()
            print(f"[Notion] Conectado para sincronización")
        except Exception as e:
            print(f"[Notion] Error conectando: {e}")

    analyzed = 0
    failed = 0
    saved = 0
    stop_event = threading.Event()

    t0 = time.time()

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            job_iter = iter(to_analyze)
            futures = {}

            def submit_next():
                if stop_event.is_set() or gemini.key_pool.exhausted:
                    return
                for url, job in job_iter:
                    future = executor.submit(analyze_single, gemini, cv_text, job, rate_limiter)
                    futures[future] = (url, job)
                    return

            for _ in range(min(args.workers, len(to_analyze))):
                submit_next()

            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    url, job = futures.pop(future)
                    try:
                        updates = future.result()
                        job.update(updates)
                        write_job_back(data, url, updates)
                        analyzed += 1
                        sync_to_notion(notion, job)

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
                                html_path, pdf_path, cl_pdf_path = cv_gen.generate(
                                    gemini, cv_text, job_data, cv_pdf_path=cv_path,
                                    cover_letter=job.get("cover_letter"),
                                    language=job.get("language", "es"),
                                )
                                if pdf_path:
                                    slug = os.path.basename(pdf_path)
                                    job["custom_cv_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                                if html_path:
                                    job["custom_cv_html"] = os.path.basename(html_path)
                                if cl_pdf_path:
                                    cl_slug = os.path.basename(cl_pdf_path)
                                    job["cover_letter_pdf_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{cl_slug}"
                                write_job_back(data, url, job)
                            except Exception as e:
                                print(f"    [CV Error] {e}")

                            if stop_event.is_set() or gemini.key_pool.exhausted:
                                continue

                            try:
                                rate_limiter.wait()
                                techs_str = ", ".join(job.get("tech_stack", [])[:10])
                                interview_prep = gemini.generate_interview_prep(
                                    cv_text=cv_text,
                                    offer_title=job["title"],
                                    company=job.get("company", ""),
                                    tech_stack=techs_str,
                                    offer_description=job.get("description", "") or job["title"],
                                    language=job.get("language", "es"),
                                )
                                job["interview_prep"] = interview_prep.model_dump()
                                rate_limiter.reset_interval()
                                write_job_back(data, url, job)
                            except Exception as e:
                                rate_limiter.backoff()
                                print(f"    [Entrevista Error] {e}")

                            if stop_event.is_set() or gemini.key_pool.exhausted:
                                continue

                            if match >= 60:
                                try:
                                    rate_limiter.wait()
                                    company_profile = gemini.research_company(
                                        company_name=job.get("company", ""),
                                        offer_title=job["title"],
                                        offer_description=job.get("description", "") or job["title"],
                                        language=job.get("language", "es"),
                                    )
                                    job["company_profile"] = company_profile.model_dump()
                                    rate_limiter.reset_interval()
                                    write_job_back(data, url, job)
                                except Exception as e:
                                    rate_limiter.backoff()
                                    print(f"    [Empresa Error] {e}")

                                if stop_event.is_set() or gemini.key_pool.exhausted:
                                    continue

                                if config.USER_PROJECTS:
                                    try:
                                        rate_limiter.wait()
                                        project_match = gemini.match_projects(
                                            cv_text=cv_text,
                                            offer_title=job["title"],
                                            offer_description=job.get("description", "") or job["title"],
                                            user_projects=config.USER_PROJECTS,
                                            language=job.get("language", "es"),
                                        )
                                        job["project_match"] = project_match.model_dump()
                                        rate_limiter.reset_interval()
                                        write_job_back(data, url, job)
                                    except Exception as e:
                                        rate_limiter.backoff()
                                        print(f"    [Proyectos Error] {e}")

                    except RuntimeError as e:
                        if "429" in str(e):
                            print(f"\n[CRITICO] Todas las API keys agotadas. Parando.")
                            stop_event.set()
                            for f in futures:
                                f.cancel()
                            break
                        failed += 1
                        rate_limiter.backoff()
                        print(f"  [Error] {job.get('title', '?')}: {e}")
                    except Exception as e:
                        failed += 1
                        rate_limiter.backoff()
                        print(f"  [Error] {job.get('title', '?')}: {e}")

                    if (analyzed + failed) % SAVE_INTERVAL == 0:
                        save_data(data)
                        saved = analyzed + failed

                if stop_event.is_set():
                    break
                submit_next()
    else:
        for url, job in to_analyze:
            if stop_event.is_set():
                break
            try:
                updates = analyze_single(gemini, cv_text, job, rate_limiter)
                job.update(updates)
                write_job_back(data, url, updates)
                analyzed += 1
                sync_to_notion(notion, job)

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
                        html_path, pdf_path, cl_pdf_path = cv_gen.generate(
                            gemini, cv_text, job_data, cv_pdf_path=cv_path,
                            cover_letter=job.get("cover_letter"),
                            language=job.get("language", "es"),
                        )
                        if pdf_path:
                            slug = os.path.basename(pdf_path)
                            job["custom_cv_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                        if html_path:
                            job["custom_cv_html"] = os.path.basename(html_path)
                        if cl_pdf_path:
                            cl_slug = os.path.basename(cl_pdf_path)
                            job["cover_letter_pdf_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{cl_slug}"
                        write_job_back(data, url, job)
                    except Exception as e:
                        print(f"    [CV Error] {e}")

                    if stop_event.is_set() or gemini.key_pool.exhausted:
                        continue

                    # Generar guía de entrevista
                    try:
                        rate_limiter.wait()
                        techs_str = ", ".join(job.get("tech_stack", [])[:10])
                        interview_prep = gemini.generate_interview_prep(
                            cv_text=cv_text,
                            offer_title=job["title"],
                            company=job.get("company", ""),
                            tech_stack=techs_str,
                            offer_description=job.get("description", "") or job["title"],
                            language=job.get("language", "es"),
                        )
                        job["interview_prep"] = interview_prep.model_dump()
                        rate_limiter.reset_interval()
                        write_job_back(data, url, job)
                    except Exception as e:
                        print(f"    [Entrevista Error] {e}")

                    if stop_event.is_set() or gemini.key_pool.exhausted:
                        continue

                    # Investigar empresa (match >= 60)
                    if match >= 60:
                        try:
                            rate_limiter.wait()
                            company_profile = gemini.research_company(
                                company_name=job.get("company", ""),
                                offer_title=job["title"],
                                offer_description=job.get("description", "") or job["title"],
                                language=job.get("language", "es"),
                            )
                            job["company_profile"] = company_profile.model_dump()
                            rate_limiter.reset_interval()
                            write_job_back(data, url, job)
                        except Exception as e:
                            print(f"    [Empresa Error] {e}")

                        if stop_event.is_set() or gemini.key_pool.exhausted:
                            continue

                        # Matching por proyectos
                        if config.USER_PROJECTS:
                            try:
                                rate_limiter.wait()
                                project_match = gemini.match_projects(
                                    cv_text=cv_text,
                                    offer_title=job["title"],
                                    offer_description=job.get("description", "") or job["title"],
                                    user_projects=config.USER_PROJECTS,
                                    language=job.get("language", "es"),
                                )
                                job["project_match"] = project_match.model_dump()
                                rate_limiter.reset_interval()
                                write_job_back(data, url, job)
                            except Exception as e:
                                print(f"    [Proyectos Error] {e}")

            except RuntimeError as e:
                if "429" in str(e):
                    print(f"\n[CRÍTICO] Todas las API keys agotadas. Parando.")
                    stop_event.set()
                    break
                failed += 1
                rate_limiter.backoff()
                print(f"  [Error] {job.get('title', '?')}: {e}")
            except Exception as e:
                failed += 1
                rate_limiter.backoff()
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
