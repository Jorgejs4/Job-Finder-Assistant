import os
import sys
from pathlib import Path
import config
from utils.cv_parser import parse_cv
from utils.gemini_client import GeminiClient
from scrapers.infojobs_scraper import InfoJobsScraper
from scrapers.linkedin_scraper import LinkedInScraper
from scrapers.indeed_scraper import IndeedScraper
from scrapers.fallback_api import FallbackJobsAPI
from notion_sync import NotionSync

def main():
    print("=" * 60)
    print("   INICIANDO ASISTENTE DE BÚSQUEDA DE EMPLEO CON IA & NOTION")
    print("=" * 60)

    # 1. Validar configuración básica e inicializar preferencias
    try:
        config.validate_config()
        config.load_preferences()
    except ValueError as e:
        print(f"[Error de Configuración] {e}")
        print("Asegúrate de configurar las variables de entorno necesarias.")
        sys.exit(1)

    # 2. Inicializar conectores
    notion_sync = NotionSync()
    gemini = GeminiClient()

    # 3. Limpiar base de datos (procesar casillas "Eliminar")
    deleted_count = notion_sync.clean_deleted_items()

    # 4. Cargar y parsear CV
    cv_path = Path(config.CV_PATH)
    if not cv_path.exists():
        print(f"[Error] No se encontró el CV en la ruta: {cv_path}")
        print("Por favor, guarda tu CV (en formato PDF, DOCX, TXT o JSON) en esa ubicación")
        print("o configura la variable de entorno 'CV_PATH' con la ruta correcta.")
        sys.exit(1)

    print(f"[CV] Leyendo y procesando currículum: {cv_path.name}...")
    try:
        cv_text = parse_cv(str(cv_path))
        print(f"[CV] CV leído correctamente. Longitud de caracteres: {len(cv_text)}")
    except Exception as e:
        print(f"[CV] Error al parsear el CV: {e}")
        sys.exit(1)

    # 5. Analizar el perfil usando Gemini
    print("[IA] Analizando perfil del CV con Gemini...")
    try:
        profile = gemini.analyze_cv(cv_text)
        print(f"[IA] Análisis completado.")
        print(f"  - Puestos recomendados: {', '.join(profile.recommended_roles)}")
        print(f"  - Habilidades detectadas: {', '.join(profile.key_skills[:8])}...")
        print(f"  - Años de experiencia: {profile.years_of_experience}")
    except Exception as e:
        print(f"[IA] Error al analizar el CV con Gemini: {e}")
        sys.exit(1)

    # 6. Recopilar ofertas de trabajo
    all_jobs = []
    # Instanciar nuestros scrapers propios
    scrapers = [
        InfoJobsScraper(),
        LinkedInScraper(),
        IndeedScraper()
    ]
    
    # Buscaremos para cada puesto recomendado por la IA
    # Para evitar saturar las APIs o el scraping, limitamos a los 4 primeros puestos más fuertes
    roles_to_search = profile.recommended_roles[:4]
    print(f"[Buscador] Buscando ofertas para los roles: {roles_to_search}")

    for role in roles_to_search:
        for scraper in scrapers:
            try:
                scraper_name = scraper.__class__.__name__
                jobs_found = scraper.scrape_jobs(role, config.DESIRED_LOCATIONS)
                all_jobs.extend(jobs_found)
            except Exception as e:
                print(f"[{scraper_name}] Error ejecutando scraping: {e}")

    # 7. Ejecutar Fallback API si es necesario
    # Si nuestros scrapers no encontraron suficientes ofertas (ej: menos de 30) o fallaron
    if len(all_jobs) < 30 and config.RAPIDAPI_KEY:
        print(f"[Buscador] Pocas ofertas encontradas ({len(all_jobs)}). Activando API de Fallback...")
        fallback = FallbackJobsAPI()
        for role in roles_to_search:
            try:
                fallback_jobs = fallback.fetch_jobs(role, config.DESIRED_LOCATIONS)
                all_jobs.extend(fallback_jobs)
            except Exception as e:
                print(f"[Fallback API] Error llamando a la API: {e}")

    # Eliminar duplicados locales que tengan el mismo link
    unique_jobs = {}
    for job in all_jobs:
        if job["link"]:
            unique_jobs[job["link"]] = job
    
    jobs_to_process = list(unique_jobs.values())
    print(f"\n[Procesamiento] Total de ofertas únicas iniciales: {len(jobs_to_process)}")

    # Filtrar por ubicación especificada o remoto (filtro preliminar)
    desired_cities = [loc for loc in config.DESIRED_LOCATIONS if loc not in ["remoto", "remote"]]
    print(f"[Filtro] Ciudades deseadas para puestos presenciales: {desired_cities}")
    
    filtered_jobs = []
    for job in jobs_to_process:
        job_loc = job.get("location", "").lower()
        job_title = job.get("title", "").lower()
        job_desc = job.get("description", "").lower()
        
        # Comprobar si tiene indicios de ser remoto en ubicación, título o descripción
        remote_keywords = ["remoto", "remote", "teletrabajo", "distancia", "virtual", "home office", "home-office"]
        is_potentially_remote = (
            any(kw in job_loc for kw in remote_keywords) or
            any(kw in job_title for kw in remote_keywords) or
            any(kw in job_desc for kw in remote_keywords)
        )
        
        # Verificar si coincide con alguna de las ciudades especificadas
        matches_city = False
        for city in desired_cities:
            if city in job_loc:
                matches_city = True
                break
                
        if is_potentially_remote or matches_city:
            filtered_jobs.append(job)
        else:
            print(f"  - [Filtro Preliminar] Saltando oferta en '{job.get('location')}' por ser presencial y no coincidir con las ciudades deseadas ({desired_cities})")

    jobs_to_process = filtered_jobs
    print(f"[Procesamiento] Ofertas que pasaron el filtro preliminar: {len(jobs_to_process)}")

    # 8. Analizar compatibilidad y subir a Notion
    new_jobs_added = 0
    analyzed_count = 0
    
    for idx, job in enumerate(jobs_to_process, 1):
        link = job["link"]
        
        # Verificar duplicados en la base de datos de Notion
        if notion_sync.check_if_job_exists(link):
            print(f"[{idx}/{len(jobs_to_process)}] Saltando oferta existente: {job['title']} en {job['company']}")
            continue
            
        # Limitar a un máximo de 15 ofertas nuevas analizadas por ejecución para respetar cuotas
        if analyzed_count >= 15:
            print(f"\n[{idx}/{len(jobs_to_process)}] Límite de 15 nuevas ofertas analizadas alcanzado. Posponiendo el resto para el siguiente cron job.")
            break
            
        print(f"\n[{idx}/{len(jobs_to_process)}] Analizando nueva oferta:")
        print(f"  - Puesto: {job['title']}")
        print(f"  - Empresa: {job['company']}")
        print(f"  - Ubicación: {job['location']}")
        print(f"  - Fuente: {job['source']}")

        # Enviar oferta e IA para scoring y consejos
        try:
            # Si no tenemos descripción de la oferta, usamos el título
            desc_for_match = job["description"] if job["description"] else job["title"]
            match_result = gemini.match_offer(
                cv_text=cv_text,
                offer_title=job["title"],
                offer_description=desc_for_match
            )
            
            # Filtrar empleos no relacionados
            if match_result.match_score < 50:
                print(f"  - [IA] Saltando oferta por baja compatibilidad ({match_result.match_score}%)")
                import time
                time.sleep(6)
                continue
                
            # Filtro de ubicación estricto según la modalidad de trabajo determinada por la IA
            work_mode = match_result.work_mode  # 'Presencial', 'Remoto', 'Híbrido'
            
            if work_mode == "Remoto":
                # Si es remoto, puede ser de cualquier sitio
                print(f"  - [Filtro Ubicación Final] Oferta remota aceptada desde cualquier origen ({job.get('location')})")
            else:
                # Si es presencial o híbrido, la ubicación debe coincidir con alguna ciudad deseada
                job_loc = job.get("location", "").lower()
                matches_city = False
                for city in desired_cities:
                    if city in job_loc:
                        matches_city = True
                        break
                if not matches_city:
                    print(f"  - [Filtro Ubicación Final] Saltando oferta clasificada como '{work_mode}' en '{job.get('location')}' por no coincidir con las ciudades deseadas ({desired_cities})")
                    import time
                    time.sleep(6)
                    continue
            
            # Combinar datos de la oferta con el resultado del análisis de IA
            job["match_score"] = match_result.match_score
            job["tech_stack"] = match_result.tech_stack
            job["tailored_advice"] = match_result.tailored_advice
            job["salary"] = str(match_result.estimated_salary)
            job["work_mode"] = match_result.work_mode
            job["salary_is_estimate"] = match_result.salary_is_estimate
            
            # Subir a Notion
            success = notion_sync.add_job_to_notion(job)
            if success:
                new_jobs_added += 1
                analyzed_count += 1
                
            # Retraso de 6 segundos para no superar el límite de 15 RPM de la API de Gemini (cuota gratis)
            import time
            time.sleep(6)
                
        except Exception as e:
            print(f"  - [Error] No se pudo analizar la oferta con IA/Notion: {e}")
            import time
            time.sleep(6)

    print("\n" + "=" * 60)
    print("                 EJECUCIÓN FINALIZADA")
    print("-" * 60)
    print(f"  - Ofertas marcadas para borrar eliminadas: {deleted_count}")
    print(f"  - Nuevas ofertas procesadas y añadidas a Notion: {new_jobs_added}")
    print("=" * 60)

if __name__ == "__main__":
    main()
