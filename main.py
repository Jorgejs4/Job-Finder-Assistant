import os
import sys
import time
from pathlib import Path
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

    all_jobs = []
    for role in roles_to_search:
        for scraper in scrapers:
            scraper_name = scraper.__class__.__name__
            try:
                jobs_found = scraper.scrape_jobs(role, config.DESIRED_LOCATIONS)
                jobs_found = jobs_found[:config.MAX_JOBS_PER_SCRAPER]
                all_jobs.extend(jobs_found)
                results.record_scraper_result(scraper_name, jobs_found)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                print(f"[{scraper_name}] Error: {error_msg}")
                results.record_scraper_result(scraper_name, [], failed=True, error_msg=error_msg)

    if len(all_jobs) < 30 and config.RAPIDAPI_KEY:
        print(f"[Buscador] Pocas ofertas ({len(all_jobs)}). Activando Fallback API...")
        fallback = FallbackJobsAPI()
        for role in roles_to_search:
            try:
                fallback_jobs = fallback.fetch_jobs(role, config.DESIRED_LOCATIONS)
                all_jobs.extend(fallback_jobs)
            except Exception as e:
                print(f"[Fallback] Error: {e}")

    unique_jobs = {}
    for job in all_jobs:
        if job.get("link"):
            unique_jobs[job["link"]] = job
    jobs_to_process = list(unique_jobs.values())
    print(f"\n[Procesamiento] Ofertas únicas: {len(jobs_to_process)}")

    source_priority = {
        "InfoJobs": 0, "LinkedIn": 1, "Indeed": 2,
        "RemoteOK": 3, "Remotive": 4, "TecnoEmpleo": 5,
        "Jobfluent": 6, "Glassdoor": 7, "API Fallback": 8,
    }
    jobs_to_process.sort(key=lambda j: source_priority.get(j.get("source", ""), 99))

    desired_cities = [loc for loc in config.DESIRED_LOCATIONS if loc not in ["remoto", "remote"]]
    print(f"[Filtro] Ciudades: {desired_cities}")

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

    jobs_to_process = filtered_jobs
    print(f"[Procesamiento] Tras filtro preliminar: {len(jobs_to_process)}")

    new_jobs_added = 0
    analyzed_count = 0

    for idx, job in enumerate(jobs_to_process, 1):
        link = job.get("link", "")

        if notion_sync.check_if_job_exists(link):
            print(f"[{idx}/{len(jobs_to_process)}] Duplicado: {job['title']}")
            continue

        if analyzed_count >= 25:
            print(f"\nLímite de 25 nuevas ofertas alcanzado.")
            break

        print(f"\n[{idx}/{len(jobs_to_process)}] {job['title']} @ {job['company']}")
        print(f"  Fuente: {job.get('source')} | Ubicación: {job.get('location')}")

        try:
            desc_for_match = job.get("description") or job["title"]
            match_result = gemini.match_offer(
                cv_text=cv_text,
                offer_title=job["title"],
                offer_description=desc_for_match,
            )

            if match_result.match_score < 35:
                print(f"  - [IA] Baja compatibilidad ({match_result.match_score}%). Saltando.")
                time.sleep(6)
                continue

            work_mode = match_result.work_mode
            if work_mode != "Remoto" and desired_cities:
                job_loc = job.get("location", "").lower()
                matches_city = any(city in job_loc for city in desired_cities)
                if not matches_city:
                    print(f"  - [Filtro] {work_mode} fuera de ciudades deseadas. Saltando.")
                    time.sleep(6)
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

            time.sleep(6)

        except Exception as e:
            print(f"  - [Error] {e}")
            time.sleep(6)

    results.set_total_added(new_jobs_added)
    results.set_analyzed_count(analyzed_count)
    json_path = results.save()

    print("\n" + "=" * 60)
    print("                 EJECUCIÓN FINALIZADA")
    print("-" * 60)
    print(f"  - Eliminadas de Notion: {deleted_count}")
    print(f"  - Nuevas añadidas: {new_jobs_added}")
    print(f"  - Analizadas por IA: {analyzed_count}")
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
