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

# Múltiples API keys de Gemini para rotación/failover
_gemini_keys_raw = os.getenv("GEMINI_API_KEYS", "")
GEMINI_API_KEYS: list = (
    [k.strip() for k in _gemini_keys_raw.split(",") if k.strip()]
    if _gemini_keys_raw
    else ([GEMINI_API_KEY] if GEMINI_API_KEY else [])
)

# API Keys para fallbacks (opcional)
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "")

# Configuración de email (opcional)
SMTP_GMAIL_USER = os.getenv("SMTP_GMAIL_USER", "")
SMTP_GMAIL_PASSWORD = os.getenv("SMTP_GMAIL_PASSWORD", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", SMTP_GMAIL_USER)

# Límite de ofertas por plataforma por ejecución
MAX_JOBS_PER_SCRAPER = int(os.getenv("MAX_JOBS_PER_SCRAPER", "50"))

# Modo de scraping: "simple" (solo HTTP) o "full" (intenta headless/Playwright)
USE_HEADLESS_SCRAPERS = os.getenv("USE_HEADLESS_SCRAPERS", "false").lower() in ("true", "1", "yes")

# Variables globales que se configurarán en la carga de preferencias
DESIRED_LOCATIONS = []
USER_CITY = os.getenv("USER_CITY", "sevilla").lower()
YEARS_OF_EXPERIENCE = 0
MIN_SALARY = None
CV_PATH = os.getenv("CV_PATH", str(DEFAULT_CV_PATH))

# === UMBRALES DE CLASIFICACIÓN Y FILTRADO ===
MIN_MATCH_TO_ARCHIVE = int(os.getenv("MIN_MATCH_TO_ARCHIVE", "10"))
MIN_MATCH_TO_DISCARD = int(os.getenv("MIN_MATCH_TO_DISCARD", "35"))
MIN_MATCH_FOR_INTERVIEW_PREP = int(os.getenv("MIN_MATCH_FOR_INTERVIEW_PREP", "50"))
MIN_MATCH_FOR_COMPANY_RESEARCH = int(os.getenv("MIN_MATCH_FOR_COMPANY_RESEARCH", "60"))
EXPERIENCE_TOLERANCE_YEARS = int(os.getenv("EXPERIENCE_TOLERANCE_YEARS", "2"))
MAX_JOBS_FOR_AI_ANALYSIS = int(os.getenv("MAX_JOBS_FOR_AI_ANALYSIS", "200"))
MAX_GEMINI_WORKERS = int(os.getenv("MAX_GEMINI_WORKERS", "3"))
GEMINI_RATE_LIMIT_SECONDS = float(os.getenv("GEMINI_RATE_LIMIT_SECONDS", "6"))
GEMINI_RATE_LIMIT_ANALYSIS = float(os.getenv("GEMINI_RATE_LIMIT_ANALYSIS", "10"))
FOLLOWUP_REMINDER_DAYS = int(os.getenv("FOLLOWUP_REMINDER_DAYS", "5"))
MAX_SALARY_SLIDER = int(os.getenv("MAX_SALARY_SLIDER", "150000"))

# === SCRAPERS: CONFIGURACIÓN CENTRALIZADA ===
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
IMPERSONATE_BROWSER = os.getenv("IMPERSONATE_BROWSER", "chrome131")
IMPERSONATE_FALLBACKS = [s.strip() for s in os.getenv("IMPERSONATE_FALLBACKS", "chrome131,chrome120,safari17_0").split(",")]
MAX_DESCRIPTION_LENGTH = int(os.getenv("MAX_DESCRIPTION_LENGTH", "500"))
INDEED_MAX_AGE_DAYS = int(os.getenv("INDEED_MAX_AGE_DAYS", "7"))
REMOTIVE_CATEGORY = os.getenv("REMOTIVE_CATEGORY", "software-dev")
GETONBRD_CATEGORY = os.getenv("GETONBRD_CATEGORY", "programming")

# === HOSTING ===
GITHUB_REPO = os.getenv("GITHUB_REPO", "Jorgejs4/Job-Finder-Assistant")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
CV_BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/results/cvs"

# === KEYWORDS DE CLASIFICACIÓN (FUENTE ÚNICA DE VERDAD) ===
REMOTE_KEYWORDS = [
    "remoto", "remote", "teletrabajo", "distancia",
    "home office", "homeoffice", "work from anywhere", "wfh",
]
REMOTE_STRICT_PHRASES = [
    "100% remote", "fully remote", "100% remoto", "trabajo 100% remoto",
    "position is remote", "puesto remoto", "modalidad remota",
    "trabajo totalmente remoto", "fully-remote", "all remote",
]
GLOBAL_KEYWORDS = [
    "worldwide", "global", "anywhere", "earth", "planet",
    "latam", "europe", "americas", "emea",
]
HYBRID_KEYWORDS = [
    "hibrido", "híbrido", "hybrid", "semipresencial",
    "% remoto", "% remote",
]
GEO_RESTRICT_KEYWORDS = [
    "must reside", "residir en", "reside in", "residents of",
    "solo para candidatos", "solo para residentes", "only for residents",
    "only for candidates", "solo locales", "solo local", "localmente",
    "must be located", "debe residir", "debe estar ubicado",
    "only available in", "solo disponible en",
]

# === RAZONES DE ARCHIVADO (CONSTANTES CENTRALIZADAS) ===
class ArchiveReason:
    LOW_MATCH = "match < {threshold}% ({actual}%)"
    GEO_RESTRICTION = "Restriccion geografica ({detail})"
    LOCATION_MISMATCH = "{mode} fuera de ciudad objetivo ({location})"
    MANUAL = "Archivado manualmente"

    @classmethod
    def low_match(cls, actual: int) -> str:
        return cls.LOW_MATCH.format(threshold=MIN_MATCH_TO_ARCHIVE, actual=actual)

    @classmethod
    def geo_restriction(cls, detail: str) -> str:
        return cls.GEO_RESTRICTION.format(detail=detail)

    @classmethod
    def location_mismatch(cls, mode: str, location: str) -> str:
        return cls.LOCATION_MISMATCH.format(mode=mode, location=location)

    SALARY_TOO_LOW = "Salario bajo el minimo ({salary} < {min_salary})"
    EXPERIENCE_TOO_HIGH = "Experiencia requerida excede la maxima ({exp} > {max_exp})"

    @classmethod
    def salary_too_low(cls, salary, min_salary) -> str:
        return cls.SALARY_TOO_LOW.format(salary=salary, min_salary=min_salary)

    @classmethod
    def experience_too_high(cls, exp, max_exp) -> str:
        return cls.EXPERIENCE_TOO_HIGH.format(exp=exp, max_exp=max_exp)


def classify_archive_reason(job: dict) -> str | None:
    """Funcion unica de verdad para determinar si un job debe archivarse.
    Retorna la razon de archivado o None si el job debe mantenerse."""
    loc = (job.get("location", "") or "").lower()
    title = (job.get("title", "") or "").lower()
    desc = (job.get("description", "") or "").lower()
    combined = f"{loc} {title} {desc}"

    # 1. Restriccion geografica
    for kw in GEO_RESTRICT_KEYWORDS:
        if kw in combined:
            return ArchiveReason.geo_restriction(kw)

    # 2. Match score demasiado bajo
    match = job.get("match_score", 0) or 0
    if match < MIN_MATCH_TO_ARCHIVE:
        return ArchiveReason.low_match(match)

    # 3. Modalidad presencial/hibrida fuera de ciudad objetivo
    wm = reclassify_work_mode(job)
    if wm != "Remoto" and USER_CITY:
        if USER_CITY not in loc:
            return ArchiveReason.location_mismatch(wm, job.get("location", "?"))

    return None


# Traducción de roles ES → EN para scrapers internacionales
ROLE_TRANSLATIONS = {
    "desarrollador backend": "backend developer",
    "desarrollador frontend": "frontend developer",
    "ingeniero de software": "software engineer",
    "devops": "devops engineer",
    "full stack": "full stack developer",
    "data engineer": "data engineer",
    "cientifico de datos": "data scientist",
    "arquitecto de software": "software architect",
    "tech lead": "tech lead",
    "product manager": "product manager",
    "ux designer": "ux designer",
    "qa engineer": "quality assurance engineer",
    "site reliability engineer": "sre",
    "cloud engineer": "cloud engineer",
    "mobile developer": "mobile developer",
    "ios developer": "ios developer",
    "android developer": "android developer",
    "python developer": "python developer",
    "java developer": "java developer",
    "javascript developer": "javascript developer",
    "react developer": "react developer",
    "node developer": "node.js developer",
    "dotnet developer": ".net developer",
    "php developer": "php developer",
    "ruby developer": "ruby developer",
    "go developer": "golang developer",
    "rust developer": "rust developer",
    "typescript developer": "typescript developer",
}

# Pipeline de aplicaciones
APPLICATION_STATUSES = [
    "Nuevo", "Revisado", "Interesado", "Aplicado",
    "Entrevista", "Oferta", "Rechazado"
]

# Umbral para fuzzy matching de duplicados
FUZZY_MATCH_THRESHOLD = int(os.getenv("FUZZY_MATCH_THRESHOLD", "85"))

# Keywords que indican puestos NO técnicos (se filtran antes de Gemini)
NON_TECH_KEYWORDS = [
    "operario", "limpieza", "camarero", "reponedor", "conductor",
    "mozo de almacén", "personal de seguridad", "cajero", "dependiente",
    "albañil", "electricista", "fontanero", "mecánico", "soldador",
    "auxiliar administrativo", "secretaria", "recepcionista",
    "atención al cliente", "call center", "telemarketing",
    "community manager", "marketing digital", "ventas",
    "recursos humanos", "contabilidad", "facturación",
    "logística", "repartidor", "mensajero", "peón",
    "monitor de guardería", "educador", "profesor",
    "enfermera", "auxiliar de enfermería", "sanitario",
    "abogado", "notario", "arbitro", "entrenador",
    "peluquero", "esteticista", "chef", "cocinero",
    "fontanería", "electricidad", "instalador",
    "data entry", "virtual assistant", "executive assistant",
    "copywriter", "redactor", "periodista",
    "project coordinator", "office manager",
    "accountant", "bookkeeper", "payroll",
    "supply chain", "warehouse", "forklift",
    "nurse", "therapist", "counselor",
    "store manager", "retail", "sales representative",
    "business development", "account manager", "client success",
    "creative strategist", "motion designer", "graphic designer",
    "content writer", "social media", "seo specialist",
    "field marketing", "brand operations", "head of creative",
    "licensed mental health", "mental health therapist",
    "athlete engagement", "level designer",
]

# Scrapers que buscan en inglés
EN_SCRAPERS = {"LinkedInScraper", "RemotiveScraper", "JoobleScraper", "GetOnBoardScraper"}

# Plataformas que publican ofertas en inglés
ENGLISH_SOURCES = {"LinkedIn", "Remotive"}


def detect_language(source: str, title: str = "", description: str = "") -> str:
    """Detecta el idioma de una oferta basándose en la fuente y contenido."""
    if source in ENGLISH_SOURCES:
        return "en"
    if source in ("InfoJobs", "Indeed", "TecnoEmpleo", "TecnoJobsScraper"):
        return "es"
    text = f"{title} {description}".lower()
    english_words = {"experience", "required", "preferred", "remote", "hybrid", "company",
                     "position", "role", "skills", "years", "knowledge", "responsibilities",
                     "benefits", "requirements", "qualifications", "team", "project"}
    spanish_words = {"experiencia", "requerido", "preferente", "remoto", "híbrido", "empresa",
                     "puesto", "rol", "habilidades", "años", "conocimientos", "responsabilidades",
                     "beneficios", "requisitos", "cualificaciones", "equipo", "proyecto"}
    en_count = sum(1 for w in english_words if w in text)
    es_count = sum(1 for w in spanish_words if w in text)
    return "en" if en_count > es_count else "es"


def normalize_work_mode(wm: str) -> str:
    """Normaliza work_mode a español unificado: 'Presencial', 'Remoto', 'Híbrido'."""
    if not wm or wm == "N/A":
        return wm or ""
    wl = str(wm).lower()
    if "remot" in wl or "teletrabaj" in wl or "distancia" in wl or "home office" in wl:
        return "Remoto"
    if "hibrid" in wl or "híbrid" in wl or "hybrid" in wl or "semipresencial" in wl:
        return "Híbrido"
    return "Presencial"


def reclassify_work_mode(job: dict) -> str:
    """
    Reclasifica work_mode usando reglas de texto sobre location, título y descripción.
    Prioridad: ubicación > título > work_mode existente > descripción (solo frases explícitas).
    Usa keywords centralizadas en module-level (REMOTE_KEYWORDS, etc.)
    """
    loc = (job.get("location", "") or "").lower()
    title = (job.get("title", "") or "").lower()
    desc = (job.get("description", "") or "").lower()
    wm_raw = (job.get("work_mode", "") or "").lower()

    def _any_in(keywords, text):
        return any(kw in text for kw in keywords)

    # 1. Ubicación: es la fuente más fiable
    if _any_in(REMOTE_KEYWORDS, loc):
        return "Remoto"
    if _any_in(GLOBAL_KEYWORDS, loc):
        return "Remoto"
    if _any_in(HYBRID_KEYWORDS, loc):
        return "Híbrido"

    # 2. Título
    if _any_in(REMOTE_KEYWORDS, title):
        return "Remoto"
    if _any_in(HYBRID_KEYWORDS, title):
        return "Híbrido"

    # 3. Descripción: SOLO frases explícitas y categóricas (antes de Gemini)
    if _any_in(REMOTE_STRICT_PHRASES, desc):
        return "Remoto"
    if _any_in(GLOBAL_KEYWORDS, desc):
        return "Remoto"
    if _any_in(HYBRID_KEYWORDS, desc):
        return "Híbrido"

    # 4. Si ubicación y título NO dicen remoto, y descripción NO tiene frases
    #    explícitas → override de Gemini (Gemini se equivoca a menudo)
    wm_norm = normalize_work_mode(wm_raw)
    if wm_norm == "Remoto":
        # Solo aceptar "Remoto" de Gemini si la ubicación es ambigua (sin city concreta)
        loc_words = loc.split()
        has_specific_city = len(loc_words) >= 2 and not _any_in(GLOBAL_KEYWORDS + REMOTE_KEYWORDS, loc)
        if has_specific_city:
            return "Presencial"

    # 5. Work_mode existente de Gemini (fallback)
    if wm_norm and wm_norm != "N/A":
        return wm_norm

    # 6. Fallback
    return "Presencial"

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
    if not GEMINI_API_KEYS:
        missing.append("GEMINI_API_KEY o GEMINI_API_KEYS")

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

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "")

# Notion sync (opcional desde el dashboard — solo se usa en pipeline)
DISABLE_NOTION_SYNC = os.getenv("DISABLE_NOTION_SYNC", "false").lower() in ("true", "1", "yes")

# Webhook configuration (opcional)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
_webhook_min = os.getenv("WEBHOOK_MIN_MATCH", "80")
WEBHOOK_MIN_MATCH = int(_webhook_min) if _webhook_min else 80

# Proyectos personales del candidato (para Feature 6: Matching por proyectos)
USER_PROJECTS = os.getenv("USER_PROJECTS", "")

# Portfolio/Certificaciones (para Feature 11)
USER_CERTIFICATIONS = os.getenv("USER_CERTIFICATIONS", "")
USER_PORTFOLIO_URL = os.getenv("USER_PORTFOLIO_URL", "")
USER_GITHUB = os.getenv("USER_GITHUB", "")
