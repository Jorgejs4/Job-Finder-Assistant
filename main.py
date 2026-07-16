import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import config
from utils.cv_parser import parse_cv
from utils.gemini_client import GeminiClient
from utils.results import ResultsManager
from utils.notifications import EmailNotifier
from scrapers.infojobs_scraper import InfoJobsScraper
from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.indeed_scraper import IndeedScraper
from scrapers.remoteok_scraper import RemoteOKScraper
from scrapers.remotive_scraper import RemotiveScraper
from scrapers.tecnobs_scraper import TecnoJobsScraper
from scrapers.jobfluent_scraper import JobfluentScraper
from scrapers.wttj_scraper import WelcomeToTheJungleScraper
from scrapers.fallback_api import FallbackJobsAPI
from notion_sync import NotionSync


def run_scraper(scraper, role, locations):
    """Ejecuta un scraper y devuelve (nombre, ofertas, error)."""
    name = scraper.__class__.__name__
    try:
        jobs = scraper.scrape_jobs(role, locations)
        return name, jobs, None
    except Exception as e:
        return name, [], f"{type(e).__name__}: {e}"


def analyze_and_upload(args):
    """Analiza una oferta con Gemini y la sube a Notion. Retorna (exito, job_data)."""
    gemini, notion_sync, cv_text, job, desired_cities = args
    link = job.get("link", "")

    if notion_sync.check_if_job_exists(link):
        return False, job, "duplicado"

    desc_for_match = job.get("description") or job["title"]
    match_result = gemini.match_offer(
        cv_text=cv_text,
        offer_title=job["title"],
        offer_description=desc_for_match,
    )

    if match_result.match_score < 35:
        return False, job, f"bajo_match_{match_result.match_score}"

    work_mode = match_result.work_mode
    if work_mode != "Remoto" and desired_cities:
        job_loc = job.get("location", "").lower()
        matches_city = any(city in job_loc for city in desired_cities)
        if not matches_city:
            return False, job, f"ubicacion_{work_mode}"

    job["match_score"] = match_result.match_score
    job["tech_stack"] = match_result.tech_stack
    job["tailored_advice"] = match_result.tailored_advice
    job["salary"] = str(match_result.estimated_salary)
    job["work_mode"] = match_result.work_mode
    job["salary_is_estimate"] = match_result.salary_is_estimate
    job["required_experience"] = match_result.required_experience

    success = notion_sync.add_job_to_notion(job)
    return success, job, "ok" if success else "notion_error"


def main():
    print("=" * 60)
    print("   INICIANDO ASISTENTE DE BÚSQUEDA DE EMPLEO CON IA & NOTION")
    print("=" * 60)

    results = ResultsManager()
    notifier = EmailNotifier()

    try:
        config.validate_config()
        config.load_preferences()
    except ValueError as e:
        print(f"[Error de Configuración] {e}")
        results.record_error(f"Configuración: {e}")
        results.save()
        sys.exit(1)

    notion_sync = NotionSync()
    gemini = GeminiClient()

    deleted_count = notion_sync.clean_deleted_items()

    cv_path = Path(config.CV_PATH)
    if not cv_path.exists():
        msg = f"No se encontró el CV en: {cv_path}"
        print(f"[Error] {msg}")
        results.record_error(msg)
        results.save()
        sys.exit(1)

    print(f"[CV] Leyendo currículum: {cv_path.name}...")
    try:
        cv_text = parse_cv(str(cv_path))
        print(f"[CV] OK. Longitud: {len(cv_text)} caracteres")
    except Exception as e:
        print(f"[CV] Error al parsear: {e}")
        results.record_error(f"CV parse: {e}")
        results.save()
        sys.exit(1)

    print("[IA] Analizando perfil con Gemini...")
    try:
        profile = gemini.analyze_cv(cv_text)
        print(f"  - Roles: {', '.join(profile.recommended_roles)}")
        print(f"  - Skills: {', '.join(profile.key_skills[:8])}...")
        print(f"  - Experiencia: {profile.years_of_experience} años")
    except Exception as e:
        print(f"[IA] Error: {e}")
        results.record_error(f"Gemini analyze_cv: {e}")
        results.save()
        sys.exit(1)

    scrapers = [
        InfoJobsScraper(),
        LinkedInScraper(),
        IndeedScraper(),
        RemoteOKScraper(),
        RemotiveScraper(),
        TecnoJobsScraper(),
        JobfluentScraper(),
        WelcomeToTheJungleScraper(),
    ]

    roles_to_search = profile.recommended_roles[:4]
    print(f"[Buscador] Roles: {roles_to_search}")
    print(f"[Buscador] Límite: {config.MAX_JOBS_PER_SCRAPER} ofertas/plataforma")

    # ── FASE 1: Scraping paralelo ──
    t0 = time.time()
    all_jobs = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for role in roles_to_search:
            for scraper in scrapers:
                future = executor.submit(run_scraper, scraper, role, config.DESIRED_LOCATIONS)
                futures[future] = scraper.__class__.__name__

        for future in as_completed(futures, timeout=120):
            name = futures[future]
            try:
                scraper_name, jobs_found, error = future.result(timeout=30)
                if error:
                    print(f"[{scraper_name}] Error: {error}")
                    results.record_scraper_result(scraper_name, [], failed=True, error_msg=error)
                else:
                    jobs_found = jobs_found[:config.MAX_JOBS_PER_SCRAPER]
                    all_jobs.extend(jobs_found)
                    results.record_scraper_result(scraper_name, jobs_found)
                    if jobs_found:
                        print(f"[{scraper_name}] +{len(jobs_found)} ofertas")
            except Exception as e:
                print(f"[{name}] Error future: {e}")
                results.record_scraper_result(name, [], failed=True, error_msg=str(e))

    if len(all_jobs) < 30 and config.RAPIDAPI_KEY:
        print(f"[Buscador] Pocas ofertas ({len(all_jobs)}). Activando Fallback API...")
        fallback = FallbackJobsAPI()
        for role in roles_to_search:
            try:
                fallback_jobs = fallback.fetch_jobs(role, config.DESIRED_LOCATIONS)
                all_jobs.extend(fallback_jobs)
            except Exception as e:
                print(f"[Fallback] Error: {e}")

    t1 = time.time()
    print(f"\n[Timing] Scraping: {t1 - t0:.1f}s")

    # ── Deduplicar y filtrar ──
    unique_jobs = {}
    for job in all_jobs:
        if job.get("link"):
            unique_jobs[job["link"]] = job
    jobs_to_process = list(unique_jobs.values())

    source_priority = {
        "InfoJobs": 0, "LinkedIn": 1, "Indeed": 2,
        "RemoteOK": 3, "Remotive": 4, "TecnoEmpleo": 5,
        "Jobfluent": 6, "Glassdoor": 7, "API Fallback": 8,
    }
    jobs_to_process.sort(key=lambda j: source_priority.get(j.get("source", ""), 99))

    desired_cities = [loc for loc in config.DESIRED_LOCATIONS if loc not in ["remoto", "remote"]]
    remote_kw = ["remoto", "remote", "teletrabajo", "distancia", "virtual", "home office"]
    filtered_jobs = []
    for job in jobs_to_process:
        job_loc = job.get("location", "").lower()
        job_title = job.get("title", "").lower()
        job_desc = job.get("description", "").lower()
        is_remote = (
            any(kw in job_loc for kw in remote_kw) or
            any(kw in job_title for kw in remote_kw) or
            any(kw in job_desc for kw in remote_kw)
        )
        matches_city = any(city in job_loc for city in desired_cities)
        if is_remote or matches_city:
            filtered_jobs.append(job)

    jobs_to_process = filtered_jobs[:50]
    print(f"[Procesamiento] {len(jobs_to_process)} ofertas tras filtros (máx 50 para análisis IA)")

    # ── FASE 2: Análisis Gemini + Notion en pipeline ──
    t2 = time.time()
    new_jobs_added = 0
    analyzed_count = 0
    skipped = {"duplicado": 0, "bajo_match": 0, "ubicacion": 0, "notion_error": 0}

    for idx, job in enumerate(jobs_to_process, 1):
        if analyzed_count >= 25:
            print(f"\nLímite de 25 nuevas ofertas alcanzado.")
            break

        link = job.get("link", "")
        print(f"\n[{idx}/{len(jobs_to_process)}] {job['title']} @ {job['company']} [{job.get('source', '')}]")

        try:
            desc_for_match = job.get("description") or job["title"]
            match_result = gemini.match_offer(
                cv_text=cv_text,
                offer_title=job["title"],
                offer_description=desc_for_match,
            )

            if match_result.match_score < 35:
                print(f"  - [IA] Baja compatibilidad ({match_result.match_score}%). Saltando.")
                skipped["bajo_match"] += 1
                time.sleep(2)
                continue

            work_mode = match_result.work_mode
            if work_mode != "Remoto" and desired_cities:
                job_loc = job.get("location", "").lower()
                matches_city = any(city in job_loc for city in desired_cities)
                if not matches_city:
                    print(f"  - [Filtro] {work_mode} fuera de ciudades deseadas. Saltando.")
                    skipped["ubicacion"] += 1
                    time.sleep(2)
                    continue

            job["match_score"] = match_result.match_score
            job["tech_stack"] = match_result.tech_stack
            job["tailored_advice"] = match_result.tailored_advice
            job["salary"] = str(match_result.estimated_salary)
            job["work_mode"] = match_result.work_mode
            job["salary_is_estimate"] = match_result.salary_is_estimate
            job["required_experience"] = match_result.required_experience

            success = notion_sync.add_job_to_notion(job)
            if success:
                new_jobs_added += 1
                analyzed_count += 1
                print(f"  - [OK] Añadida a Notion (match: {match_result.match_score}%)")
            else:
                skipped["notion_error"] += 1

            time.sleep(2)

        except Exception as e:
            print(f"  - [Error] {e}")
            skipped["notion_error"] += 1
            time.sleep(2)

    t3 = time.time()
    print(f"\n[Timing] Análisis IA + Notion: {t3 - t2:.1f}s")
    print(f"[Timing] Total: {t3 - t0:.1f}s")

    results.set_total_added(new_jobs_added)
    results.set_analyzed_count(analyzed_count)
    results.save()

    print("\n" + "=" * 60)
    print("                 EJECUCIÓN FINALIZADA")
    print("-" * 60)
    print(f"  - Eliminadas de Notion: {deleted_count}")
    print(f"  - Analizadas por IA: {analyzed_count}")
    print(f"  - Nuevas añadidas: {new_jobs_added}")
    print(f"  - Skipped: {skipped}")
    print(f"  - Tiempo total: {t3 - t0:.1f}s")
    print("=" * 60)

    scraper_stats = results.get_scraper_stats()
    top_jobs = results.get_top_jobs(10)
    email_errors = results.run_data.get("errors", [])

    notifier.send_summary(
        jobs_added=new_jobs_added,
        jobs_analyzed=analyzed_count,
        scraper_stats=scraper_stats,
        top_jobs=top_jobs,
        errors=email_errors,
    )


if __name__ == "__main__":
    main()
