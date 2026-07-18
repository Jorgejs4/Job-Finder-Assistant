import os
import sys
import time
import threading
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
from utils.feedback_manager import FeedbackManager
from scrapers.infojobs_scraper import InfoJobsScraper
from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.indeed_scraper import IndeedScraper
from scrapers.remotive_scraper import RemotiveScraper
from scrapers.tecnobs_scraper import TecnoJobsScraper
from scrapers.jobfluent_scraper import JobfluentScraper
from scrapers.jooble_scraper import JoobleScraper
from scrapers.getonbrd_scraper import GetOnBoardScraper
from notion_sync import NotionSync


class RateLimiter:
    """Thread-safe rate limiter. Ensures min_interval seconds between ANY two Gemini calls.
    Auto-backs off on 429 errors."""

    def __init__(self, min_interval=6.0):
        self.base_interval = min_interval
        self.min_interval = min_interval
        self.last_call_time = 0.0
        self.lock = threading.Lock()

    def wait(self):
        while True:
            with self.lock:
                now = time.time()
                wait_time = self.min_interval - (now - self.last_call_time)
                if wait_time <= 0:
                    self.last_call_time = now
                    return
            time.sleep(min(wait_time, 1.0))

    def backoff(self):
        """Called on 429 — quadruple the interval temporarily."""
        with self.lock:
            self.min_interval = min(self.min_interval * 4, 120.0)
            print(f"\n[RateLimit] 429 detectado. Intervalo aumentado a {self.min_interval:.0f}s")

    def reset_interval(self):
        """Slowly reduce interval after successful calls."""
        with self.lock:
            if self.min_interval > self.base_interval:
                self.min_interval = max(self.base_interval, self.min_interval * 0.7)
                print(f"\n[RateLimit] Éxito. Intervalo reducido a {self.min_interval:.1f}s")


def _analyze_single_job(args):
    """Worker function for Gemini analysis. Returns (job, match_result, error)."""
    gemini, job, cv_text, rate_limiter, stop_event = args
    if stop_event.is_set():
        return job, None, "Stop signal received"
    try:
        rate_limiter.wait()
        if stop_event.is_set():
            return job, None, "Stop signal received"
        desc_for_match = job.get("description") or job["title"]
        experience_hint = job.get("experience_hint", 0)
        language = config.detect_language(job.get("source", ""), job.get("title", ""), desc_for_match)
        match_result = gemini.match_offer(
            cv_text=cv_text,
            offer_title=job["title"],
            offer_description=desc_for_match,
            experience_hint=experience_hint,
            language=language,
        )
        rate_limiter.reset_interval()
        return job, match_result, None
    except RuntimeError as e:
        if "429" in str(e):
            rate_limiter.backoff()
        return job, None, str(e)
    except Exception as e:
        return job, None, str(e)


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
    feedback_mgr = FeedbackManager()

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
    with ThreadPoolExecutor(max_workers=8) as executor:
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

    # Bucket existing jobs by first 3 chars for fast fuzzy lookup
    existing_buckets = {}
    for ej in existing_jobs:
        ekey = f"{ej['title']} {ej['company']}".lower().strip()
        if len(ekey) >= 3:
            bucket = ekey[:3]
            existing_buckets.setdefault(bucket, []).append((ekey, ej))

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
        bucket = job_key[:3] if len(job_key) >= 3 else job_key
        for existing_key, _ in existing_buckets.get(bucket, []):
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
        "Remotive": 3, "TecnoEmpleo": 4,
        "Jobfluent": 5, "Jooble": 6, "GetOnBoard": 7, "API Fallback": 8,
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

    jobs_to_process = keyword_filtered[:200]
    print(f"[Procesamiento] {len(jobs_to_process)} ofertas tras filtros (máx 200 para análisis IA)")

    # Batch dedup: cargar URLs de Notion una sola vez
    existing_urls = set(notion_sync.get_existing_urls())
    skipped = {"duplicado": 0, "bajo_match": 0, "ubicacion": 0, "notion_error": 0, "cuota_gemini": False}

    # Pre-filter: remove duplicates and obviously non-matching jobs before Gemini
    pre_filtered = []
    for job in jobs_to_process:
        link = job.get("link", "")
        if link in existing_urls:
            skipped["duplicado"] += 1
            continue
        pre_filtered.append(job)
    print(f"[PreFiltro] {len(pre_filtered)} ofertas tras pre-dedup (se eliminaron {skipped['duplicado']} duplicados exactos)")

    # ── FASE 2: Análisis Gemini paralelo + Notion ──
    t2 = time.time()
    rate_limiter = RateLimiter(min_interval=10.0)
    new_jobs_added = 0
    analyzed_count = 0
    high_match_jobs = []
    stop_event = threading.Event()
    MAX_GEMINI_WORKERS = 3

    # ── Procesar feedback pendiente de CVs anteriores ──
    pending_feedback = feedback_mgr.get_pending()
    if pending_feedback:
        print(f"\n[Feedback] {len(pending_feedback)} CVs pendientes de regenerar con feedback")
        existing_data = results._load_data()
        for fb in pending_feedback:
            fb_job_id = fb.get("job_id", "")
            fb_title = fb.get("title", "")
            fb_company = fb.get("company", "")
            fb_text = fb.get("feedback", "")
            print(f"  - Regenerando: {fb_title} @ {fb_company}")
            print(f"    Feedback: {fb_text[:80]}...")

            # Buscar el job original en data.json para re-analizar
            found_job = None
            for run in existing_data.get("runs", []):
                for j in run.get("jobs", []):
                    if j.get("title") == fb_title and j.get("company") == fb_company:
                        found_job = j
                        break
                if found_job:
                    break

            if not found_job:
                print(f"    [Warning] No se encontró el job original en data.json, saltando feedback")
                feedback_mgr.mark_done(fb_job_id)
                continue

            try:
                # Regenerar CV directamente con feedback (1 llamada Gemini, no 2)
                rate_limiter.wait()
                job_data_for_cv = {
                    "title": fb_title,
                    "company": fb_company,
                    "tech_stack": found_job.get("tech_stack", []),
                    "tailored_advice": found_job.get("tailored_advice", ""),
                }
                html_path, pdf_path, cl_pdf_path = cv_gen.regenerate_with_feedback(
                    gemini, cv_text, job_data_for_cv, fb_text, cv_pdf_path=str(cv_path)
                )
                if pdf_path:
                    slug = os.path.basename(pdf_path)
                    cv_url = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                    # Actualizar URL en data.json
                    for run in existing_data.get("runs", []):
                        for j in run.get("jobs", []):
                            if j.get("title") == fb_title and j.get("company") == fb_company:
                                j["custom_cv_url"] = cv_url
                                if cl_pdf_path:
                                    cl_slug = os.path.basename(cl_pdf_path)
                                    j["cover_letter_pdf_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{cl_slug}"
                                break
                    with open(results.data_path, "w", encoding="utf-8") as f:
                        import json
                        json.dump(existing_data, f, ensure_ascii=False, indent=2)
                    # Actualizar Notion si la oferta existe
                    existing_job = notion_sync.find_existing_job(fb_title, fb_company)
                    if existing_job:
                        notion_sync.update_cv_url(existing_job["page_id"], cv_url)
                    feedback_mgr.mark_done(fb_job_id)
                    print(f"    [OK] CV regenerado con feedback")
                else:
                    print(f"    [Error] No se pudo regenerar el CV")
                    feedback_mgr.mark_done(fb_job_id)
            except Exception as e:
                print(f"    [Error] Regenerando CV: {e}")
                feedback_mgr.mark_done(fb_job_id)

    print(f"\n[Análisis] Procesando {min(len(pre_filtered), 200)} ofertas con 3 hilos Gemini...")

    pending_futures = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        for job in pre_filtered[:200]:
            if stop_event.is_set():
                break
            future = executor.submit(_analyze_single_job, (gemini, job, cv_text, rate_limiter, stop_event))
            pending_futures.append(future)

        for future in as_completed(pending_futures):
            if analyzed_count >= 200:
                stop_event.set()
                break
            if stop_event.is_set():
                break

            job, match_result, error = future.result()

            if error:
                if "429" in error:
                    print(f"\n[CRÍTICO] Cuota Gemini agotada. Deteniendo análisis.")
                    skipped["cuota_gemini"] = True
                    stop_event.set()
                    break
                skipped["notion_error"] += 1
                continue

            print(f"  - {job['title']} @ {job['company']}: match {match_result.match_score}%", flush=True)

            if match_result.match_score < 35:
                skipped["bajo_match"] += 1
                continue

            if config.MIN_SALARY and match_result.estimated_salary and not match_result.salary_is_estimate:
                if match_result.estimated_salary < config.MIN_SALARY:
                    skipped["bajo_match"] += 1
                    continue

            max_exp = config.YEARS_OF_EXPERIENCE + 2
            if max_exp > 0 and match_result.required_experience > max_exp:
                skipped["ubicacion"] += 1
                continue

            work_mode = match_result.work_mode
            if work_mode != "Remoto" and desired_cities:
                job_loc = job.get("location", "").lower()
                matches_city = any(city in job_loc for city in desired_cities)
                if not matches_city:
                    skipped["ubicacion"] += 1
                    continue

            job["match_score"] = match_result.match_score
            job["tech_stack"] = match_result.tech_stack
            job["tailored_advice"] = match_result.tailored_advice
            job["salary"] = str(match_result.estimated_salary)
            job["work_mode"] = match_result.work_mode
            job["salary_is_estimate"] = match_result.salary_is_estimate
            job["required_experience"] = match_result.required_experience

            if match_result.cover_letter:
                job["cover_letter"] = match_result.cover_letter

            language = config.detect_language(job.get("source", ""), job.get("title", ""), job.get("description", "") or job["title"])
            job["language"] = language

            if notion_sync._find_prop("CV") and match_result.cv_skills:
                try:
                    job_data_for_cv = {
                        "title": job["title"],
                        "company": job.get("company", ""),
                        "tech_stack": job.get("tech_stack", []),
                        "tailored_advice": match_result.tailored_advice or "",
                    }
                    html_path, pdf_path, cl_pdf_path = cv_gen.generate(
                        gemini, cv_text, job_data_for_cv,
                        cv_pdf_path=str(cv_path),
                        cover_letter=match_result.cover_letter,
                        language=language,
                    )
                    if pdf_path:
                        slug = os.path.basename(pdf_path)
                        cv_url = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{slug}"
                        job["custom_cv_url"] = cv_url
                        if html_path:
                            job["custom_cv_html"] = os.path.basename(html_path)
                        if cl_pdf_path:
                            cl_slug = os.path.basename(cl_pdf_path)
                            job["cover_letter_pdf_url"] = f"https://raw.githubusercontent.com/Jorgejs4/Job-Finder-Assistant/main/results/cvs/{cl_slug}"
                except Exception as e:
                    print(f"    [CV] Error generando CV: {e}")

            # Generar guía de entrevista para ofertas con match >= 50
            if match_result.match_score >= 50:
                try:
                    rate_limiter.wait()
                    techs_str = ", ".join(job.get("tech_stack", [])[:10])
                    interview_prep = gemini.generate_interview_prep(
                        cv_text=cv_text,
                        offer_title=job["title"],
                        company=job.get("company", ""),
                        tech_stack=techs_str,
                        offer_description=desc_for_match,
                        language=language,
                    )
                    job["interview_prep"] = interview_prep.model_dump()
                    rate_limiter.reset_interval()
                except Exception as e:
                    print(f"    [Entrevista] Error generando interview prep: {e}")

            # Investigar empresa para ofertas con match >= 60
            if match_result.match_score >= 60:
                try:
                    rate_limiter.wait()
                    company_profile = gemini.research_company(
                        company_name=job.get("company", ""),
                        offer_title=job["title"],
                        offer_description=desc_for_match,
                        language=language,
                    )
                    job["company_profile"] = company_profile.model_dump()
                    rate_limiter.reset_interval()
                except Exception as e:
                    print(f"    [Empresa] Error investigando empresa: {e}")

                # Matching por proyectos para match >= 60
                if config.USER_PROJECTS:
                    try:
                        rate_limiter.wait()
                        project_match = gemini.match_projects(
                            cv_text=cv_text,
                            offer_title=job["title"],
                            offer_description=desc_for_match,
                            user_projects=config.USER_PROJECTS,
                            language=language,
                        )
                        job["project_match"] = project_match.model_dump()
                        rate_limiter.reset_interval()
                    except Exception as e:
                        print(f"    [Proyectos] Error en match de proyectos: {e}")

            success = notion_sync.add_job_to_notion(job)
            if success:
                new_jobs_added += 1
                analyzed_count += 1
                high_match_jobs.append(job)
            else:
                skipped["notion_error"] += 1

    t3 = time.time()
    print(f"\n[Timing] Análisis IA + Notion: {t3 - t2:.1f}s")
    print(f"[Timing] Total: {t3 - t0:.1f}s")

    results.set_total_added(new_jobs_added)
    results.set_analyzed_count(analyzed_count)
    results.run_data["profile_skills"] = profile.key_skills
    results.run_data["profile_roles"] = profile.recommended_roles
    results.run_data["profile_summary"] = profile.summary
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
        quota_exceeded=skipped.get("cuota_gemini", False),
    )

    # Webhook notifications
    webhook.notify_high_match_jobs(high_match_jobs, scraper_stats)
    webhook.notify_summary(new_jobs_added, analyzed_count, scraper_stats)


if __name__ == "__main__":
    main()
