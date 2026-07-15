from typing import List, Dict, Any
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
import config


class IndeedScraper(BaseScraper):
    def scrape_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        """
        Scraper para Indeed.
        Nota: Indeed utiliza Cloudflare de manera muy agresiva y suele devolver 403 Forbidden 
        cuando se ejecuta desde rangos de IP de servidores como GitHub Actions. 
        Este scraper está diseñado como un intento de mejor esfuerzo, y fallará con gracia 
        si es bloqueado para que actúe el fallback de la API.
        """
        print(f"[Indeed] Buscando ofertas para '{search_query}'...")
        jobs = []
        
        search_locations = locations if locations else ["España"]
        
        for loc in search_locations:
            api_loc = config.get_location_for("indeed", loc)
            print(f"[Indeed] Buscando en ubicación: {api_loc}")
            
            # Indeed España
            url = "https://es.indeed.com/jobs"
            params = {
                "q": search_query,
                "l": api_loc,
                "fromage": 3 # ofertas de los últimos 3 días
            }
            
            try:
                # Intentamos obtener el HTML
                response = self.client.get(url, params=params)
                if response.status_code == 403:
                    print(f"[Indeed] Petición bloqueada por Cloudflare (Código 403). Se activará el fallback.")
                    return []
                elif response.status_code != 200:
                    print(f"[Indeed] Error en la petición ({response.status_code})")
                    continue
                
                soup = BeautifulSoup(response.text, "html.parser")
                # Intentar parsear las tarjetas de Indeed
                # Históricamente usan divs con la clase 'job_seen_beacon' o similar
                cards = soup.find_all("div", class_="job_seen_beacon")
                print(f"[Indeed] Se encontraron {len(cards)} tarjetas de empleo.")
                
                for card in cards:
                    try:
                        title_tag = card.find("h2", class_="jobTitle")
                        if not title_tag:
                            continue
                        
                        a_tag = title_tag.find("a")
                        title = title_tag.text.strip()
                        link = "https://es.indeed.com" + a_tag["href"] if a_tag else ""
                        
                        company_tag = card.find("span", class_="companyName") or card.find("span", {"data-testid": "company-name"})
                        company = company_tag.text.strip() if company_tag else "No especificada"
                        
                        loc_tag = card.find("div", class_="companyLocation") or card.find("div", {"data-testid": "text-location"})
                        location = loc_tag.text.strip() if loc_tag else api_loc
                        
                        # Snippet de descripción
                        desc_tag = card.find("div", class_="job-snippet") or card.find("table", class_="jobCard_mainContent")
                        description = desc_tag.text.strip() if desc_tag else ""
                        
                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "link": link,
                            "description": description,
                            "date_posted": "Reciente",
                            "source": "Indeed"
                        })
                    except Exception as e:
                        print(f"[Indeed] Error al parsear tarjeta individual: {e}")
                        continue
                        
            except Exception as e:
                print(f"[Indeed] Error en la conexión/scraping de Indeed: {e}")
                
        return jobs
