import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde .env para desarrollo local
load_dotenv()

# Rutas del proyecto
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CV_PATH = BASE_DIR / "cv.pdf"

# Credenciales de API
NOTION_TOKEN = os.getenv("NOTION_TOKEN")

def _sanitize_db_id(db_id: str) -> str:
    if not db_id:
        return ""
    # Si es una URL completa, nos quedamos con el final
    if "/" in db_id:
        db_id = db_id.split("/")[-1]
    # Quitar parámetros de vista (?v=...)
    db_id = db_id.split("?")[0]
    return db_id.strip()

NOTION_DATABASE_ID = _sanitize_db_id(os.getenv("NOTION_DATABASE_ID"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# API Keys para fallbacks (opcional)
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "")

# Configuración de email (opcional)
SMTP_GMAIL_USER = os.getenv("SMTP_GMAIL_USER", "")
SMTP_GMAIL_PASSWORD = os.getenv("SMTP_GMAIL_PASSWORD", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", SMTP_GMAIL_USER)

# Límite de ofertas por plataforma por ejecución
MAX_JOBS_PER_SCRAPER = int(os.getenv("MAX_JOBS_PER_SCRAPER", "50"))

# Variables globales que se configurarán en la carga de preferencias
DESIRED_LOCATIONS = []
YEARS_OF_EXPERIENCE = 0
MIN_SALARY = None
CV_PATH = os.getenv("CV_PATH", str(DEFAULT_CV_PATH))

# Mapping de ubicaciones: expande nombres cortos a strings completos para cada scraper
LOCATION_MAP = {
    "sevilla": {
        "linkedin": "Sevilla, Andalucía, España",
        "indeed": "Sevilla, España",
        "infojobs": "sevilla",
        "jsearch": "Sevilla Spain",
        "tecnoempleo": "sevilla",
        "jobfluent": "Sevilla",
        "jooble": "Sevilla",
        "getonbrd": "Sevilla",
        "display": "Sevilla, Andalucía, España",
    },
    "madrid": {
        "linkedin": "Madrid, España",
        "indeed": "Madrid, España",
        "infojobs": "madrid",
        "jsearch": "Madrid Spain",
        "tecnoempleo": "madrid",
        "jobfluent": "Madrid",
        "jooble": "Madrid",
        "getonbrd": "Madrid",
        "display": "Madrid, España",
    },
    "barcelona": {
        "linkedin": "Barcelona, Cataluña, España",
        "indeed": "Barcelona, España",
        "infojobs": "barcelona",
        "jsearch": "Barcelona Spain",
        "tecnoempleo": "barcelona",
        "jobfluent": "Barcelona",
        "jooble": "Barcelona",
        "getonbrd": "Barcelona",
        "display": "Barcelona, Cataluña, España",
    },
    "valencia": {
        "linkedin": "Valencia, España",
        "indeed": "Valencia, España",
        "infojobs": "valencia",
        "jsearch": "Valencia Spain",
        "tecnoempleo": "valencia",
        "jobfluent": "Valencia",
        "jooble": "Valencia",
        "getonbrd": "Valencia",
        "display": "Valencia, España",
    },
    "remoto": {
        "linkedin": "Remote",
        "indeed": "Remoto",
        "infojobs": "remoto",
        "jsearch": "Remote",
        "tecnoempleo": "remoto",
        "jobfluent": "Remote",
        "jooble": "España",
        "getonbrd": "Remote",
        "display": "Remoto",
    },
    "remote": {
        "linkedin": "Remote",
        "indeed": "Remote",
        "infojobs": "remoto",
        "jsearch": "Remote",
        "tecnoempleo": "remoto",
        "jobfluent": "Remote",
        "jooble": "España",
        "getonbrd": "Remote",
        "display": "Remote",
    },
}


def get_location_for(scraper_name: str, location_key: str) -> str:
    """Devuelve la ubicación formateada para un scraper dado."""
    key = location_key.lower().strip()
    if key in LOCATION_MAP:
        return LOCATION_MAP[key].get(scraper_name, key.title())
    # Si no está en el mapping, devolver con capitalización básica
    return key.title() if key not in ("remoto", "remote") else "Remote"

def validate_config():
    """Valida que las credenciales críticas estén configuradas."""
    missing = []
    if not NOTION_TOKEN:
        missing.append("NOTION_TOKEN")
    if not NOTION_DATABASE_ID:
        missing.append("NOTION_DATABASE_ID")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    
    if missing:
        raise ValueError(
            f"Faltan variables de entorno requeridas: {', '.join(missing)}. "
            "Por favor, configúralas en tu archivo .env o en los secretos de GitHub."
        )

def load_preferences():
    """
    Carga las preferencias de búsqueda. Si no están en el entorno y la ejecución es
    interactiva (local en consola), las pregunta al usuario. Si no, usa valores por defecto.
    """
    global DESIRED_LOCATIONS, YEARS_OF_EXPERIENCE, MIN_SALARY
    
    is_interactive = not os.getenv("GITHUB_ACTIONS") and sys.stdin.isatty()

    # 1. Ubicaciones
    locations_env = os.getenv("DESIRED_LOCATIONS")
    if not locations_env:
        if is_interactive:
            print("\n--- CONFIGURACIÓN DE PREFERENCIAS DE BÚSQUEDA ---")
            val = input("Introduce las ubicaciones de búsqueda separadas por comas (ej. Sevilla, Remoto): ")
            locations_env = val if val.strip() else "Remoto"
        else:
            locations_env = "Remoto"
            
    DESIRED_LOCATIONS = [
        loc.strip().lower() 
        for loc in locations_env.split(",") 
        if loc.strip()
    ]

    # 2. Años de experiencia
    exp_env = os.getenv("YEARS_OF_EXPERIENCE")
    if exp_env is None:
        if is_interactive:
            val = input("Introduce los años de experiencia requeridos (ej. 2, o presiona Enter para omitir): ")
            exp_env = val if val.strip() else "0"
        else:
            exp_env = "0"
    try:
        YEARS_OF_EXPERIENCE = int(exp_env) if exp_env.strip() else 0
    except ValueError:
        YEARS_OF_EXPERIENCE = 0

    # 3. Salario mínimo (opcional)
    sal_env = os.getenv("MIN_SALARY")
    if sal_env is None:
        if is_interactive:
            val = input("Introduce el salario mínimo anual deseado (ej. 30000, o presiona Enter para omitir/no filtrar): ")
            sal_env = val if val.strip() else ""
        else:
            sal_env = ""
            
    if sal_env.strip():
        try:
            MIN_SALARY = int(sal_env)
        except ValueError:
            MIN_SALARY = None
    else:
        MIN_SALARY = None
