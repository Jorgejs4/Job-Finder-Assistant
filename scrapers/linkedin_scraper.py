import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class LinkedInScraper(BaseScraper):
    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Scrapea ofertas de empleo de LinkedIn usando su API de búsqueda pública (guest).
        """
        print(f"[LinkedIn] Buscando ofertas para '{search_query}'...")
        jobs = []

        search_locations = locations if locations else ["Spain"]

        for loc in search_locations:
            api_loc = config.get_location_for("linkedin", loc)
            print(f"[LinkedIn] Buscando en ubicación: {api_loc}")
            
            # URL de búsqueda pública de LinkedIn
            url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            params = {
                "keywords": search_query,
                "location": api_loc,
                "start": 0
            }
            
            html = self.get_html(url, params=params)
            if not html:
                continue
                
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.find_all("li")
            
            print(f"[LinkedIn] Se encontraron {len(cards)} tarjetas de empleo brutas en {api_loc}.")
            
            # Limitar a máximo 8 ofertas por ubicación para evitar rate limiting en GitHub Actions
            count = 0
            for card in cards:
                if count >= 8:
                    break
                    
                try:
                    # Enlace e ID del trabajo
                    link_tag = card.find("a", class_=re.compile("base-card__full-link|job-search-card"))
                    if not link_tag or not link_tag.get("href"):
                        continue
                    link = link_tag["href"].split("?")[0] # Limpiar query params
                    
                    # Extraer ID del trabajo de la URL (suele ser el último grupo de dígitos en el enlace)
                    job_id_match = re.findall(r"\d+", link)
                    job_id = job_id_match[-1] if job_id_match else None
                    
                    # Título
                    title_tag = card.find("h3", class_=re.compile("base-search-card__title|job-search-card__title"))
                    title = title_tag.text.strip() if title_tag else "No especificado"
                    
                    # Empresa
                    company_tag = card.find("h4", class_=re.compile("base-search-card__subtitle|job-search-card__subtitle"))
                    company = company_tag.text.strip() if company_tag else "No especificada"
                    
                    # Ubicación
                    loc_tag = card.find("span", class_=re.compile("job-search-card__location"))
                    location = loc_tag.text.strip() if loc_tag else api_loc
                    
                    # Fecha de publicación
                    date_tag = card.find("time", class_=re.compile("job-search-card__listdate"))
                    date_posted = date_tag.get("datetime") if date_tag else (date_tag.text.strip() if date_tag else "Reciente")
                    
                    # Obtener la descripción completa llamando al endpoint interno de detalle (si tenemos ID)
                    description = "Descripción no disponible en vista previa."
                    if job_id:
                        import time
                        time.sleep(2)  # Retraso para evitar rate-limiting (429) de LinkedIn
                        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
                        detail_html = self.get_html(detail_url)
                        if detail_html:
                            detail_soup = BeautifulSoup(detail_html, "html.parser")
                            # La descripción suele estar en una clase de descripción o similar
                            desc_tag = detail_soup.find("div", class_=re.compile("description__text|show-more-less-html__markup"))
                            if desc_tag:
                                description = desc_tag.text.strip()
                    
                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "link": link,
                        "description": description,
                        "date_posted": date_posted,
                        "source": "LinkedIn"
                    })
                    count += 1
                    
                except Exception as e:
                    print(f"[LinkedIn] Error al procesar tarjeta: {e}")
                    continue
                    
        print(f"[LinkedIn] Total acumulado de ofertas filtradas: {len(jobs)}")
        return jobs
