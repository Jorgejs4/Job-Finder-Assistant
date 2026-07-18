from typing import List, Dict, Any
import httpx
import config


class FallbackJobsAPI:
    """
    Cliente de API de búsqueda de empleo como plan de contingencia (fallback).
    Utiliza JSearch de RapidAPI que consolida múltiples fuentes (Indeed, LinkedIn, ZipRecruiter).
    Requiere RAPIDAPI_KEY en las variables de entorno.
    Nota: El plan gratis de JSearch solo cubre resultados de US/UK.
    """
    def __init__(self):
        self.api_key = config.RAPIDAPI_KEY
        self.host = "jsearch.p.rapidapi.com"
        self.headers = {
            "x-rapidapi-key": self.api_key if self.api_key else "",
            "x-rapidapi-host": self.host
        }

    def fetch_jobs(self, search_query: str, locations: List[str]) -> List[Dict[str, Any]]:
        if not self.api_key:
            print("[Fallback API] RAPIDAPI_KEY no configurada. Saltando fallback de API.")
            return []
            
        print(f"[Fallback API] Ejecutando búsqueda fallback para '{search_query}'...")
        jobs = []
        
        search_locations = locations if locations else ["Spain"]
        
        with httpx.Client(headers=self.headers, timeout=20.0) as client:
            for loc in search_locations:
                api_loc = config.get_location_for("jsearch", loc)
                query_str = f"{search_query} {api_loc}"
                print(f"[Fallback API] Buscando: '{query_str}'")
                
                url = "https://jsearch.p.rapidapi.com/search-v2"
                params = {
                    "query": query_str,
                    "page": "1",
                    "num_pages": "1",
                }
                
                try:
                    response = client.get(url, params=params)
                    if response.status_code != 200:
                        print(f"[Fallback API] Error en API ({response.status_code}): {response.text[:200]}")
                        continue
                        
                    data = response.json()
                    if data.get("status") == "ERROR":
                        print(f"[Fallback API] Error de la API: {data.get('error', {}).get('message', 'Unknown')}")
                        continue

                    results = data.get("data", {}).get("jobs", [])
                    if not results:
                        print(f"[Fallback API] Sin resultados para '{query_str}' (el plan gratis puede no cubrir España)")
                        continue

                    print(f"[Fallback API] Encontradas {len(results)} ofertas en la API.")
                    
                    for item in results:
                        is_remote = item.get("job_is_remote", False)
                        city = item.get("job_city")
                        country = item.get("job_country", "ES")
                        
                        location_parts = []
                        if city:
                            location_parts.append(city)
                        if is_remote:
                            location_parts.append("Remoto")
                        
                        location = ", ".join(location_parts) if location_parts else ("Remoto" if is_remote else country)
                        
                        apply_link = item.get("job_apply_link", "")
                        if not apply_link:
                            apply_link = item.get("job_google_link", "")
                        
                        date_posted = item.get("job_posted_at_datetime_utc", "Reciente")[:10]
                        
                        jobs.append({
                            "title": item.get("job_title", "Puesto no especificado"),
                            "company": item.get("employer_name", "Empresa no especificada"),
                            "location": location,
                            "link": apply_link,
                            "description": item.get("job_description", ""),
                            "date_posted": date_posted,
                            "source": f"{item.get('job_publisher', 'API Fallback')}"
                        })
                        
                except Exception as e:
                    print(f"[Fallback API] Error al llamar a la API de RapidAPI: {e}")
                    continue
                    
        return jobs
