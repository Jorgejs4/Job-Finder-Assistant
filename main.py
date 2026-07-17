import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from thefuzz import fuzz
import config
from utils.cv_parser import parse_cv
from utils.gemini_client import GeminiClient
from utils.results import ResultsManager
from utils.notifications import EmailNotifier
from utils.webhooks import WebhookNotifier
from utils.cv_generator import CVGenerator
from scrapers.infojobs_scraper import InfoJobsScraper
from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.indeed_scraper import IndeedScraper
from scrapers.remoteok_scraper import RemoteOKScraper
from scrapers.remotive_scraper import RemotiveScraper
from scrapers.tecnobs_scraper import TecnoJobsScraper
from scrapers.jobfluent_scraper import JobfluentScraper
from scrapers.jooble_scraper import JoobleScraper
from scrapers.getonbrd_scraper import GetOnBoardScraper
from notion_sync import NotionSync


def run_scraper(scraper, role, locations):
    """Ejecuta un scraper y devuelve (nombre, ofertas, error)."""
    name = scraper.__class__.__name__
    try:
        jobs = scraper.scrape_jobs(role, locations)
        return name, jobs, None
    except Exception as e:
        return name, [], f"{type(e).__name__}: {e}"


def main():
    print("=" * 60)
    print("   INICIANDO ASISTENTE DE BÚSQUEDA DE EMPLEO CON IA & NOTION")
    print("=" * 60)

    results = ResultsManager()
    notifier = EmailNotifier()
    webhook = WebhookNotifier()
    cv_gen = CVGenerator()

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
        JoobleScraper(),
        GetOnBoardScraper(),
    ]

    roles_to_search = profile.recommended_roles[:4]

    # ── BÚSQUEDA MULTILINGÜE ──
    roles_en = []
    for role in roles_to_search:
        role_lower = role.lower().strip()
        if role_lower in config.ROLE_TRANSLATIONS:
            roles_en.append(config.ROLE_TRANSLATIONS[role_lower])
        else:
            roles_en.append(role)

    print(f"[Buscador] Roles (ES): {roles_to_search}")
    print(f"[Buscador] Roles (EN): {roles_en}")
    print(f"[Buscador] Límite: {config.MAX_JOBS_PER_SCRAPER} ofertas/plataforma")

    # ── FASE 1: Scraping paralelo ──
    t0 = time.time()
    all_jobs = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for role_es, role_en in zip(roles_to_search, roles_en):
            for scraper in scrapers:
                scraper_name = scraper.__class__.__name__
                role_to_use = role_en if scraper_name in config.EN_SCRAPERS else role_es
                future = executor.submit(run_scraper, scraper, role_to_use, config.DESIRED_LOCATIONS)
                futures[future] = scraper_name

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
        print(f"[Buscador] Pocas ofertas ({len(all_jobs)}). Usando fallback API...")
        try:
            from scrapers.fallback_api import FallbackJobsAPI
            fallback = FallbackJobsAPI()
            for role in roles_to_search:
                try:
                    fallback_jobs = fallback.fetch_jobs(role, config.DESIRED_LOCATIONS)
                    all_jobs.extend(fallback_jobs)
                except Exception as e:
                    print(f"[Fallback] Error: {e}")
        except ImportError:
            print("[Fallback] fallback_api no disponible")

    t1 = time.time()
    print(f"\n[Timing] Scraping: {t1 - t0:.1f}s")

    # ── DEDUPLICACIÓN FUZZY ──
    print(f"\n[Dedup] {len(all_jobs)} ofertas totales. Obteniendo ofertas existentes de Notion...")
    existing_jobs = notion_sync.get_all_jobs_for_fuzzy()
    print(f"[Dedup] {len(existing_jobs)} ofertas en Notion")

    unique_jobs = {}
    duplicates_fuzzy = 0
    for job in all_jobs:
        link = job.get("link", "")
        if not link:
            continue

        if link in unique_jobs:
            continue

        job_key = f"{job.get('title', '')} {job.get('company', '')}".lower().strip()
        if not job_key:
            unique_jobs[link] = job
            continue

        is_duplicate = False
        for existing in existing_jobs:
            existing_key = f"{existing['title']} {existing['company']}".lower().strip()
            if not existing_key:
                continue
            similarity = fuzz.token_sort_ratio(job_key, existing_key)
            if similarity >= config.FUZZY_MATCH_THRESHOLD:
                is_duplicate = True
                duplicates_fuzzy += 1
                break

        if not is_duplicate:
            unique_jobs[link] = job

    print(f"[Dedup] {duplicates_fuzzy} duplicados fuzzy eliminados, {len(unique_jobs)} únicas")

    jobs_to_process = list(unique_jobs.values())

    source_priority = {
        "InfoJobs": 0, "LinkedIn": 1, "Indeed": 2,
        "RemoteOK": 3, "Remotive": 4, "TecnoEmpleo": 5,
        "Jobfluent": 6, "Jooble": 7, "GetOnBoard": 8, "API Fallback": 9,
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

    # Filtro por keywords no-tech (ahorra llamadas a Gemini)
    before_keyword = len(filtered_jobs)
    keyword_filtered = []
    for job in filtered_jobs:
        title_lower = job.get("title", "").lower()
        desc_lower = job.get("description", "").lower()
        combined = f"{title_lower} {desc_lower}"
        if any(kw in combined for kw in config.NON_TECH_KEYWORDS):
            continue
        keyword_filtered.append(job)
    keyword_skipped = before_keyword - len(keyword_filtered)
    if keyword_skipped:
        print(f"[Filtro] {keyword_skipped} ofertas no-tech eliminadas por keywords")

    jobs_to_process = keyword_filtered[:50]
    print(f"[Procesamiento] {len(jobs_to_process)} ofertas tras filtros (máx 50 para análisis IA)")

    # Batch dedup: cargar URLs de Notion una sola vez
    existing_urls = set(notion_sync.get_existing_urls())

    # ── FASE 2: Análisis Gemini + Notion en pipeline ──
    t2 = time.time()
    new_jobs_added = 0
    analyzed_count = 0
    high_match_jobs = []
    skipped = {"duplicado": 0, "bajo_match": 0, "ubicacion": 0, "notion_error": 0}

    for idx, job in enumerate(jobs_to_process, 1):
        if analyzed_count >= 25:
            print(f"\nLímite de 25 nuevas ofertas alcanzado.")
            break

        link = job.get("link", "")
        print(f"\n[{idx}/{len(jobs_to_process)}] {job['title']} @ {job['company']} [{job.get('source', '')}]")

        if link in existing_urls:
            print(f"  - [Dedup] Ya existe en Notion. Saltando.")
            skipped["duplicado"] += 1
            continue

        try:
            desc_for_match = job.get("description") or job["title"]
            experience_hint = job.get("experience_hint", 0)
            match_result = gemini.match_offer(
                cv_text=cv_text,
                offer_title=job["title"],
                offer_description=desc_for_match,
                experience_hint=experience_hint,
            )

            if match_result.match_score < 35:
                print(f"  - [IA] Baja compatibilidad ({match_result.match_score}%). Saltando.")
                skipped["bajo_match"] += 1
                time.sleep(2)
                continue

            # Filtro por salario mínimo (solo si la oferta indica salario explícito)
            if config.MIN_SALARY and match_result.estimated_salary and not match_result.salary_is_estimate:
                if match_result.estimated_salary < config.MIN_SALARY:
                    print(f"  - [Filtro] Salario {match_result.estimated_salary}€ < mínimo {config.MIN_SALARY}€. Saltando.")
                    skipped["bajo_match"] += 1
                    time.sleep(2)
                    continue

            # Filtro por experiencia máxima (exigir más de tu experiencia + margen)
            max_exp = config.YEARS_OF_EXPERIENCE + 2
            if max_exp > 0 and match_result.required_experience > max_exp:
                print(f"  - [Filtro] Experiencia requerida {match_result.required_experience} años > máximo {max_exp}. Saltando.")
                skipped["ubicacion"] += 1
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

            # Carta de presentación del match combinado
            if match_result.cover_letter:
                job["cover_letter"] = match_result.cover_letter
                print(f"  - [IA] Carta de presentación generada")

            # CV personalizado del match combinado
            if notion_sync._find_prop("CV") and match_result.cv_skills:
                try:
                    cv_content = {
                        "name": "",
                        "contact": "",
                        "summary": match_result.cv_summary or "",
                        "experience": match_result.cv_experience_adapted or [],
                        "education": [],
                        "skills": match_result.cv_skills or [],
                        "projects": match_result.cv_projects or [],
                    }
                    cv_path = cv_gen.generate_from_data(cv_content, job["title"], job.get("company", ""))
                    if cv_path:
                        slug = os.path.basename(cv_path)
                        cv_url = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                        job["custom_cv_url"] = cv_url
                        print(f"  - [CV] PDF personalizado generado")
                except Exception as e:
                    print(f"  - [CV] Error generando CV: {e}")

            success = notion_sync.add_job_to_notion(job)
            if success:
                new_jobs_added += 1
                analyzed_count += 1
                high_match_jobs.append(job)
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
    print(f"  - Duplicados fuzzy: {duplicates_fuzzy}")
    print(f"  - Skipped: {skipped}")
    print(f"  - Tiempo total: {t3 - t0:.1f}s")
    print("=" * 60)

    scraper_stats = results.get_scraper_stats()
    top_jobs = results.get_top_jobs(10)
    email_errors = results.run_data.get("errors", [])

    # Stats de la ejecución anterior para comparar
    prev_stats = None
    existing_data = results._load_data()
    if len(existing_data.get("runs", [])) > 0:
        prev_run = existing_data["runs"][0]
        prev_stats = {
            "total_added": prev_run.get("_total_added", 0),
            "analyzed": prev_run.get("_analyzed_count", 0),
        }

    notifier.send_summary(
        jobs_added=new_jobs_added,
        jobs_analyzed=analyzed_count,
        scraper_stats=scraper_stats,
        top_jobs=top_jobs,
        errors=email_errors,
        previous_run_stats=prev_stats,
    )

    # Webhook notifications
    webhook.notify_high_match_jobs(high_match_jobs, scraper_stats)
    webhook.notify_summary(new_jobs_added, analyzed_count, scraper_stats)


if __name__ == "__main__":
    main()
