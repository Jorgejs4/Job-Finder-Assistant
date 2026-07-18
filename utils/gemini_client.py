import json
import threading
import google.generativeai as genai
from pydantic import BaseModel, Field
from typing import List, Optional
import config


class KeyPool:
    """Pool de API keys de Gemini con failover automático en 429."""

    def __init__(self, keys: list):
        self._keys = list(keys)
        self._index = 0
        self._lock = threading.Lock()
        self._exhausted = False
        self._configure()

    def _mask_key(self, key: str) -> str:
        if len(key) <= 8:
            return "****"
        return f"{key[:6]}...{key[-4:]}"

    def _configure(self):
        key = self._keys[self._index]
        genai.configure(api_key=key)
        print(f"[Gemini] API key activa: {self._mask_key(key)} (#{self._index + 1}/{len(self._keys)})")

    def current_key(self) -> str:
        return self._keys[self._index]

    def rotate(self) -> bool:
        """Rotar a la siguiente key. Devuelve False si todas agotadas."""
        with self._lock:
            next_index = self._index + 1
            if next_index >= len(self._keys):
                self._exhausted = True
                print(f"\n[Gemini] Todas las {len(self._keys)} API keys agotadas.")
                return False
            self._index = next_index
            self._configure()
            return True

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def total_keys(self) -> int:
        return len(self._keys)

    @property
    def active_index(self) -> int:
        return self._index


# Configurar el SDK de Gemini con la primera key disponible
if config.GEMINI_API_KEYS:
    genai.configure(api_key=config.GEMINI_API_KEYS[0])
elif config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)

class ProfileAnalysis(BaseModel):
    recommended_roles: List[str] = Field(
        description="Lista de títulos de puestos de trabajo ideales para buscar basados en el CV (máximo 4, ej: 'React Developer', 'Frontend Engineer')."
    )
    key_skills: List[str] = Field(
        description="Lista de habilidades técnicas y herramientas principales (ej: ['Python', 'Docker', 'React'])."
    )
    years_of_experience: float = Field(
        description="Años estimados de experiencia laboral detectados en el CV."
    )
    summary: str = Field(
        description="Un breve resumen profesional del candidato en español."
    )

class OfferMatchBasic(BaseModel):
    """Evaluación básica: match score, stack y modalidad. Solo 3 campos para flash-lite."""
    match_score: int = Field(
        description="Puntuación de coincidencia del 0 al 100 de qué tan bien encaja el CV en la oferta. Sé riguroso y objetivo, puntuando bajo si el rol no coincide en absoluto."
    )
    tech_stack: List[str] = Field(
        description="Lista de tecnologías y herramientas requeridas por la oferta (ej: ['Docker', 'AWS', 'FastAPI']). Extrae las tecnologías reales mencionadas en la oferta."
    )
    work_mode: str = Field(
        description="Modalidad de trabajo detectada en la oferta. Debe ser exactamente uno de estos valores: 'Presencial', 'Remoto', 'Híbrido'."
    )

class OfferMatchDetails(BaseModel):
    """Detalles de la oferta: salario, experiencia y consejos."""
    estimated_salary: int = Field(
        description="Salario estimado anual bruto en euros (EUR). Si la oferta NO especifica salario, estima uno realista para este puesto en España."
    )
    salary_is_estimate: bool = Field(
        description="True si el salario fue estimado porque la oferta no lo mencionaba."
    )
    required_experience: int = Field(
        description="Años de experiencia que pide la empresa (0=junior, 5=senior sin número). Máximo 20."
    )
    tailored_advice: str = Field(
        description="Consejos concretos en español para adaptar el CV a esta oferta específica."
    )

class CVCustomization(BaseModel):
    """Carta de presentación + resumen. Solo 2 campos de texto."""
    cover_letter: str = Field(
        description="Carta de presentación personalizada, 150-250 palabras, 3-4 párrafos. Tono profesional pero cercano."
    )
    cv_summary: str = Field(
        description="Resumen profesional de 3-4 líneas optimizado para este puesto."
    )

class CVExperience(BaseModel):
    """Experiencia, skills y proyectos. 3 campos estructurados."""
    cv_experience_adapted: List[dict] = Field(
        default_factory=list,
        description="Experiencia laboral reordenada. Cada item: {role: str, company: str, period: str, description: str}"
    )
    cv_skills: List[str] = Field(
        default_factory=list,
        description="Habilidades más relevantes para este puesto, ordenadas por relevancia."
    )
    cv_projects: List[dict] = Field(
        default_factory=list,
        description="Proyectos reformulados. Cada item: {name: str, description: str}"
    )

class CVContent(BaseModel):
    """Contenido estructurado de un CV personalizado para una oferta específica."""
    name: str = Field(description="Nombre completo del candidato")
    contact: str = Field(description="Contacto: email | teléfono | ubicación")
    summary: str = Field(
        description="Resumen profesional de 3-4 líneas. Debe incluir: cargo objetivo, años de experiencia, especialización y tecnologías principales. Ejemplo: 'Backend Software Engineer con 4 años de experiencia desarrollando APIs REST escalables con Java, Spring Boot y PostgreSQL.'"
    )
    experience: List[dict] = Field(
        description="Experiencia laboral. Cada item: {role, company, period, description: list[str]}. La description DEBE ser una lista de bullet points con logros CUANTIFICADOS (%, tiempo, usuarios, métricas). Ejemplo: ['Desarrollé 12 APIs REST en Spring Boot que redujeron tiempos de respuesta en un 40%', 'Migré monolito a microservicios, reduciendo despliegues de 2h a 15min']. NUNCA usar verbos genéricos sin métricas."
    )
    education: List[dict] = Field(
        description="Formación académica. Cada item: {degree, institution, year}"
    )
    skills: dict = Field(
        description="Habilidades AGRUPADAS por categoría. Ejemplo: {\"Backend\": [\"Java\", \"Spring Boot\", \"Hibernate\"], \"Bases de datos\": [\"PostgreSQL\", \"MySQL\"], \"Cloud\": [\"AWS\", \"Docker\"]}. NUNCA hacer una lista plana mixta."
    )
    projects: List[dict] = Field(
        description="Proyectos relevantes reformulados. Cada item: {name, description}. No incluir proyectos básicos (CRUD, calculadora, to-do list). Incluir proyectos completos, open source, SaaS, herramientas propias."
    )

class SkillsGap(BaseModel):
    missing_skills: List[dict] = Field(
        description="Lista de habilidades faltantes ordenadas por frecuencia. Cada item: {skill: str, count: int, percentage: float, advice: str}"
    )
    summary: str = Field(
        description="Resumen ejecutivo del análisis de skills gap en español."
    )
    recommendations: List[str] = Field(
        description="Lista de 3-5 recomendaciones concretas para cerrar las brechas más importantes."
    )

class InterviewPrep(BaseModel):
    technical_questions: List[dict] = Field(
        default_factory=list,
        description="Lista de 5-8 preguntas técnicas probables con respuestas sugeridas. Cada item: {question: str, answer: str}"
    )
    behavioral_questions: List[dict] = Field(
        default_factory=list,
        description="Lista de 3-5 preguntas comportamentales (STAR method) con respuestas sugeridas. Cada item: {question: str, answer: str}"
    )
    key_topics: List[str] = Field(
        default_factory=list,
        description="Lista de 3-5 temas clave que el candidato debe repasar para esta entrevista."
    )
    preparation_tips: List[str] = Field(
        default_factory=list,
        description="Lista de 3-5 consejos específicos para preparar esta entrevista concreta."
    )


class CompanyProfile(BaseModel):
    name: str = Field(description="Nombre de la empresa")
    industry: str = Field(description="Sector/industria de la empresa")
    size: str = Field(description="Tamaño aproximado: 'startup' (1-50), 'mediana' (50-500), 'grande' (500+), 'enterprise' (5000+)")
    tech_stack: List[str] = Field(description="Tecnologías principales que usa la empresa según la oferta")
    culture: str = Field(description="Cultura laboral descrita (ej: 'orientada a resultados, agile, remoto-first')")
    pros: List[str] = Field(description="3-5 puntos a favor de trabajar ahí")
    cons: List[str] = Field(description="2-3 posibles inconvenientes o cosas a tener en cuenta")
    salary_range: str = Field(description="Rango salarial aproximado para este tipo de puesto en esta empresa")
    remote_friendly: bool = Field(description="True si la empresa es friendly con remoto")
    recommendation: str = Field(description="Breve recomendación personalizada (1-2 oraciones) sobre si vale la pena aplicar")


class ProjectMatch(BaseModel):
    project_relevance: int = Field(
        description="Puntuación de 0-100 indicando cuánto encajan los proyectos personales del candidato con lo que busca la empresa."
    )
    matching_projects: List[str] = Field(
        description="Lista de proyectos del candidato que son relevantes para esta oferta."
    )
    missing_project_types: List[str] = Field(
        description="Tipos de proyecto que el candidato NO tiene pero que serían relevantes para este puesto."
    )
    project_advice: str = Field(
        description="Consejo concreto en 1-2 oraciones sobre qué proyecto personal crear o mejorar para destacar en esta oferta."
    )

class GeminiClient:
    def __init__(self):
        import os
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

        # Key pool para rotación/failover
        keys = config.GEMINI_API_KEYS or ([config.GEMINI_API_KEY] if config.GEMINI_API_KEY else [])
        if not keys:
            raise ValueError("No hay API keys de Gemini configuradas.")
        self.key_pool = KeyPool(keys)
        self.model = genai.GenerativeModel(self.model_name)

    def _on_429(self) -> bool:
        """Intenta rotar key tras 429. Devuelve True si hay nueva key, False si agotada."""
        if self.key_pool.rotate():
            self.model = genai.GenerativeModel(self.model_name)
            return True
        return False

    def _generate_with_retry(self, prompt: str, schema, max_retries: int = 3) -> str:
        """
        Realiza la llamada a la API de Gemini con reintentos.
        Reintenta en 429 (rotando key) y en errores de validación (respuesta incompleta).
        """
        import time
        from google.api_core.exceptions import ResourceExhausted
        from pydantic import ValidationError
        
        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2
        )
        
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                text = response.text
                # Validar que el JSON es parseable y completo
                data = json.loads(text)
                schema(**data)  # Pydantic validation
                return text
            except ResourceExhausted:
                last_error = "429"
                if self._on_429():
                    wait_time = min(5 * (attempt + 1), 30)
                    print(f"\n[Gemini] 429 → key #{self.key_pool.active_index + 1}. Reintentando en {wait_time}s... (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError("429 - Todas las API keys de Gemini agotadas.")
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)[:100]
                wait_time = min(3 * (attempt + 1), 15)
                print(f"\n[Gemini] Respuesta incompleta/inválida. Reintentando en {wait_time}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                raise e
                
        raise RuntimeError(f"Gemini falló tras {max_retries} intentos. Último error: {last_error}")

    def analyze_cv(self, cv_text: str) -> ProfileAnalysis:
        """
        Analiza el texto de un CV para extraer roles sugeridos, 
        habilidades clave y años de experiencia en formato estructurado.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            print("[Gemini] Usando MOCK_GEMINI para análisis de CV.")
            return ProfileAnalysis(
                recommended_roles=["Desarrollador Python", "Desarrollador Java", "Full-stack Developer", "Backend Engineer"],
                key_skills=["Python", "JavaScript", "Java", "SQL", "Docker", "Git"],
                years_of_experience=1.5,
                summary="Desarrollador de software junior con formación en CFGS de Desarrollo de Aplicaciones Multiplataforma e Ingeniería Industrial, y experiencia desarrollando proyectos propios de IA y automatización."
            )

        prompt = f"""
        Analiza el siguiente Currículum Vitae (CV) o perfil profesional. 
        Extrae la información clave y sugiere hasta 4 títulos de trabajo específicos que se adapten perfectamente a este perfil para realizar una búsqueda de empleo efectiva en portales de empleo.
        Asegúrate de que los puestos recomendados estén alineados estrictamente con el perfil del candidato.
        Para maximizar la cantidad de ofertas encontradas en portales españoles (como InfoJobs o Indeed España), incluye tanto el término en inglés como su traducción o equivalente común en español (por ejemplo, 'Desarrollador Junior' y 'Junior Developer', 'Frontend Developer' y 'Desarrollador Frontend', etc.) como roles separados en la lista de recomendados.

        Texto del CV:
        ---
        {cv_text}
        ---
        """
        
        response_text = self._generate_with_retry(prompt, ProfileAnalysis)
        
        # Cargar el resultado JSON estructurado
        data = json.loads(response_text)
        return ProfileAnalysis(**data)

    def match_offer(self, cv_text: str, offer_title: str, offer_description: str, experience_hint: int = 0, language: str = "es") -> OfferMatchBasic:
        """
        Compara el CV con una oferta de empleo y devuelve un Match Score, 
        el stack tecnológico detectado, modalidad, salario y consejos de optimización.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            # Smart Mock basado en el título y descripción
            title_lower = offer_title.lower()
            desc_lower = offer_description.lower()
            
            # Determinar match score basado en las palabras clave del título en comparación con el perfil
            match_score = 0
            if any(x in title_lower for x in ["desarrollador", "developer", "engineer", "programador", "analista"]):
                match_score += 40
            if "python" in title_lower or "python" in desc_lower:
                match_score += 30
            if "javascript" in title_lower or "javascript" in desc_lower or "react" in title_lower or "react" in desc_lower:
                match_score += 15
            if "java" in title_lower or "java" in desc_lower:
                match_score += 15
            if "c" in title_lower:
                match_score += 5
            
            # Penalizar fuertemente roles no relacionados
            if any(x in title_lower for x in ["cementerio", "operario", "reponedor", "limpieza", "camarero", "conductor", "mozo"]):
                match_score = 5  # Muy bajo para que el filtro de >=50 lo descarte
                
            match_score = max(5, min(100, match_score))
            
            # Extraer stack tecnológico dinámicamente
            possible_techs = ["Python", "JavaScript", "Java", "C", "Docker", "Git", "SQL", "React", "Node.js", "Django", "FastAPI", "AWS", "Oracle"]
            tech_stack = []
            for tech in possible_techs:
                if tech.lower() in title_lower or tech.lower() in desc_lower:
                    tech_stack.append(tech)
            if not tech_stack:
                tech_stack = ["Python", "Git"]
                
            # Clasificar modalidad dinámicamente
            work_mode = "Presencial"
            if "remoto" in title_lower or "remoto" in desc_lower or "remote" in title_lower or "remote" in desc_lower or "teletrabajo" in desc_lower:
                work_mode = "Remoto"
            elif "hibrido" in desc_lower or "híbrido" in desc_lower or "hybrid" in desc_lower or "flexibilidad" in desc_lower:
                work_mode = "Híbrido"
                
            # Estimar salario dinámicamente
            import re
            salary_match = re.search(r'(\d{2})[\s.]?(\d{3})', offer_description)
            if salary_match:
                estimated_salary = int(salary_match.group(1) + salary_match.group(2))
            else:
                if "python" in title_lower:
                    estimated_salary = 35000
                elif "desarrollador" in title_lower or "developer" in title_lower:
                    estimated_salary = 30000
                else:
                    estimated_salary = 24000
                    
            # Consejos adaptados
            if "python" in title_lower:
                tailored_advice = "Resalta tu proyecto de tienda online con recomendador de IA en Python y tu curso Elements of AI."
            elif "java" in title_lower:
                tailored_advice = "Destaca tu formación superior en CFGS DAM y tus conocimientos de base de datos Oracle y Java."
            else:
                tailored_advice = f"Destaca tus conocimientos en {', '.join(tech_stack[:3])} en tu CV. Resalta los proyectos de tu portafolio relacionados con estas herramientas."
                
            print(f"  - [Smart Mock] Match: {match_score}%, Stack: {tech_stack}, Mod: {work_mode}")
            return OfferMatchBasic(
                match_score=match_score,
                tech_stack=tech_stack,
                work_mode=work_mode,
            )

        lang_name = "español" if language == "es" else "English"
        salary_hint = "euros (EUR)" if language == "es" else "US dollars (USD)"
        country_hint = "España" if language == "es" else "the country where the job is located"
        mode_values = "'Presencial', 'Remoto', 'Híbrido'" if language == "es" else "'On-site', 'Remote', 'Hybrid'"

        prompt = f"""
        Eres un reclutador experto. 
        Compara el siguiente currículum con la oferta de empleo y genera SOLO lo siguiente:

        1. MATCH_SCORE: Puntuación de compatibilidad (0-100). Si el puesto es manual o no relacionado con desarrollo (operario, limpieza, etc.), pon por debajo de 10.
        2. TECH_STACK: Tecnologías y herramientas requeridas en la oferta. Extrae tecnologías reales del texto.
        3. WORK_MODE: Modalidad exacta: {mode_values}.

        Currículum del candidato:
        ---
        {cv_text}
        ---

        Oferta de Empleo:
        Puesto: {offer_title}
        Descripción:
        {offer_description}
        """

        response_text = self._generate_with_retry(prompt, OfferMatchBasic)
        
        data = json.loads(response_text)
        return OfferMatchBasic(**data)

    def match_details(self, cv_text: str, offer_title: str, offer_description: str, match_result: OfferMatchBasic, language: str = "es") -> OfferMatchDetails:
        """
        Genera detalles de la oferta: salario, experiencia y consejos.
        Llamada separada de match_basic para no saturar flash-lite.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            import re
            salary_match = re.search(r'(\d{2})[\s.]?(\d{3})', offer_description)
            estimated_salary = int(salary_match.group(1) + salary_match.group(2)) if salary_match else 28000
            return OfferMatchDetails(
                estimated_salary=estimated_salary,
                salary_is_estimate=not bool(salary_match),
                required_experience=0,
                tailored_advice=f"Adapta tu CV destacando experiencia con {', '.join(match_result.tech_stack[:3])}.",
            )

        lang_name = "español" if language == "es" else "English"
        salary_hint = "euros (EUR)" if language == "es" else "US dollars (USD)"
        country_hint = "España" if language == "es" else "the country where the job is located"

        prompt = f"""
        Analiza esta oferta de empleo y genera SOLO lo siguiente:

        1. ESTIMATED_SALARY: Salario anual bruto estimado en {salary_hint}. Si no se menciona, estima uno realista para {country_hint}. Devuelve un número entero.
        2. SALARY_IS_ESTIMATE: True si estimaste el salario porque la oferta no lo mencionaba.
        3. REQUIRED_EXPERIENCE: Años de experiencia que pide la empresa (0=junior, 5=senior sin número). Máximo 20.
        4. TAILORED_ADVICE: Consejos concretos en {lang_name} para adaptar el CV a esta oferta. Sé específico y personalizado.

        Contexto del análisis previo:
        - Match Score: {match_result.match_score}/100
        - Tecnologías de la oferta: {', '.join(match_result.tech_stack[:8])}

        Oferta de Empleo:
        Puesto: {offer_title}
        Descripción:
        {offer_description}
        """

        response_text = self._generate_with_retry(prompt, OfferMatchDetails)
        
        data = json.loads(response_text)
        return OfferMatchDetails(**data)

    def customize_cv_text(self, cv_text: str, offer_title: str, offer_description: str, match_result: OfferMatchBasic, language: str = "es") -> CVCustomization:
        """Llamada 3a: genera cover letter + cv summary (2 campos de texto)."""
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return CVCustomization(
                cover_letter=f"Estimado equipo de reclutamiento,\n\nMe dirijo a ustedes para presentar mi candidatura a la posición de {offer_title}.\n\nUn cordial saludo.",
                cv_summary="Desarrollador de software con formación en desarrollo de aplicaciones multiplataforma.",
            )

        lang_name = "español" if language == "es" else "English"
        no_phrase = '"Me dirijo a ustedes para..."' if language == "es" else '"I am writing to express my interest in..."'
        techs_str = ", ".join(match_result.tech_stack[:8])

        prompt = f"""
        Genera carta de presentación y resumen profesional para este candidato.

        CONTEXTO: Match {match_result.match_score}/100. Tech: {techs_str}

        1. COVER_LETTER: Carta personalizada en {lang_name} (150-250 palabras, 3-4 párrafos).
           - Menciona tecnologías concretas del CV relevantes para ESTA oferta
           - No uses frases genéricas como {no_phrase}
           - Termina con call-to-action

        2. CV_SUMMARY: Resumen de 3-4 líneas optimizado para ESTE puesto. En {lang_name}.

        CV: ---
        {cv_text}
        ---

        Oferta: {offer_title}
        {offer_description}
        """

        response_text = self._generate_with_retry(prompt, CVCustomization)
        data = json.loads(response_text)
        return CVCustomization(**data)

    def customize_cv_data(self, cv_text: str, offer_title: str, offer_description: str, match_result: OfferMatchBasic, language: str = "es") -> CVExperience:
        """Llamada 3b: genera experiencia, skills y proyectos (3 campos estructurados)."""
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return CVExperience(
                cv_experience_adapted=[],
                cv_skills=match_result.tech_stack[:5],
                cv_projects=[],
            )

        lang_name = "español" if language == "es" else "English"
        techs_str = ", ".join(match_result.tech_stack[:8])

        prompt = f"""
        Reorganiza la experiencia, skills y proyectos del candidato para esta oferta.

        CONTEXTO: Match {match_result.match_score}/100. Tech: {techs_str}

        1. CV_EXPERIENCE_ADAPTED: Reorganiza experiencia en {lang_name}.
           Cada item: {{"role": str, "company": str, "period": str, "description": str (2-3 líneas)}}

        2. CV_SKILLS: Habilidades más relevantes ordenadas por relevancia.

        3. CV_PROJECTS: Proyectos reformulados en {lang_name}.
           Cada item: {{"name": str, "description": str (1-2 líneas)}}

        CV: ---
        {cv_text}
        ---

        Oferta: {offer_title}
        {offer_description}
        """

        response_text = self._generate_with_retry(prompt, CVExperience)
        data = json.loads(response_text)
        return CVExperience(**data)

    def generate_cover_letter(self, cv_text: str, offer_title: str, company: str, offer_description: str, language: str = "es") -> str:
        """
        Genera una carta de presentación personalizada para una oferta específica.
        Devuelve el texto en formato markdown.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return f"""Estimado equipo de {company},

Me dirijo a ustedes para expresar mi interés en la posición de {offer_title}.

Con mi experiencia en desarrollo de software y mi formación técnica, estoy convencido de poder aportar valor a su equipo. Mi perfil combina conocimientos técnicos sólidos con una mentalidad de aprendizaje continuo.

Quedo a su disposición para ampliar cualquier información.

Un cordial saludo."""

        lang_name = "español" if language == "es" else "English"
        no_phrase = '"Me dirijo a ustedes para..."' if language == "es" else '"I am writing to express my interest in..."'

        prompt = f"""
        Eres un experto en redacción de cartas de presentación profesionales.
        Genera una carta de presentación personalizada en {lang_name} para esta oferta de empleo.

        REGLAS:
        - La carta debe tener 3-4 párrafos cortos (máximo 4 oraciones cada uno)
        - Sé específico: menciona tecnologías y experiencias concretas del CV relevantes para ESTA oferta
        - Tono profesional pero cercano, sin ser genérico
        - No uses frases hechas como {no_phrase}
        - Enfócate en POR QUÉ el candidato es buen fit para ESTE puesto específico
        - Menciona 2-3 tecnologías específicas que el candidato domina y que pide la oferta
        - Termina con un call-to-action natural
        - Formato: Markdown simple (## para título, párrafos normales)
        - Extensión: 150-250 palabras máximo

        CV del candidato:
        ---
        {cv_text}
        ---

        Oferta:
        Puesto: {offer_title}
        Empresa: {company}
        Descripción:
        {offer_description}
        """

        import time
        from google.api_core.exceptions import ResourceExhausted

        for attempt in range(2):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except ResourceExhausted:
                if attempt < 1:
                    if self._on_429():
                        print(f"\n[Gemini] 429 → cover_letter. Key #{self.key_pool.active_index + 1}. Esperando 5s...")
                        time.sleep(5)
                    else:
                        raise RuntimeError("429 - Todas las API keys agotadas en cover_letter.")
                else:
                    raise RuntimeError("429 - Todas las API keys agotadas en cover_letter.")
            except Exception as e:
                raise e
        raise RuntimeError("429 - Todas las API keys agotadas en cover_letter.")

    def analyze_skills_gap(self, cv_text: str, jobs_data: list) -> SkillsGap:
        """
        Analiza las ofertas más recientes y determina qué habilidades son
        más demandadas pero no están en el CV del candidato.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return SkillsGap(
                missing_skills=[
                    {"skill": "Kubernetes", "count": 12, "percentage": 48.0, "advice": "Considera obtener la certificación CKA o completa tutoriales prácticos"},
                    {"skill": "AWS", "count": 10, "percentage": 40.0, "advice": "AWS Academy tiene cursos gratuitos; empieza por Cloud Practitioner"},
                    {"skill": "TypeScript", "count": 8, "percentage": 32.0, "advice": "Migra un proyecto personal de JS a TS para ganar experiencia práctica"},
                ],
                summary="De las 25 ofertas analizadas, las habilidades más demandadas que no tienes son Kubernetes (48%), AWS (40%) y TypeScript (32%). Estas son tendencias claras del mercado.",
                recommendations=[
                    "Prioriza aprender Kubernetes - es la skill faltante más demandada",
                    "Obtén una certificación AWS Cloud Practitioner",
                    "Migra tus proyectos existentes de JavaScript a TypeScript"
                ]
            )

        # Formatear las ofertas para el prompt
        jobs_summary = []
        for i, job in enumerate(jobs_data[:25], 1):
            techs = ", ".join(job.get("tech_stack", [])[:10])
            jobs_summary.append(f"{i}. {job.get('title', 'N/A')} @ {job.get('company', 'N/A')} — Skills: {techs}")

        jobs_text = "\n".join(jobs_summary)

        prompt = f"""
        Eres un analista de mercado laboral tech. Analiza las ofertas de empleo y el CV del candidato para identificar SKILLS GAP.

        TAREAS:
        1. Extrae TODAS las tecnologías/habilidades mencionadas en las ofertas
        2. Compara con las habilidades del CV
        3. Identifica las habilidades que más se repiten en ofertas PERO NO están en el CV
        4. Ordena por frecuencia (las más demandadas primero)
        5. Para cada skill faltante, da un consejo concreto para adquirirla

        CV del candidato:
        ---
        {cv_text}
        ---

        Ofertas analizadas (últimas 25):
        {jobs_text}
        """

        response_text = self._generate_with_retry(prompt, SkillsGap)
        data = json.loads(response_text)
        return SkillsGap(**data)

    def generate_cv_content(self, cv_text: str, offer_title: str, company: str, advice: str, tech_stack: str, feedback: str = None, language: str = "es") -> dict:
        """
        Genera contenido de CV de alta calidad para una oferta específica.
        Sigue las 10 reglas de un CV técnico profesional.
        Devuelve un dict con: name, contact, summary, experience, education, skills (dict), projects.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return {
                "name": "Candidato",
                "contact": "email@ejemplo.com | +34 600 000 000 | Madrid",
                "summary": "Backend Software Engineer con 2 años de experiencia desarrollando APIs REST con Python, Django y PostgreSQL. Especializado en arquitecturas escalables y despliegue continuo.",
                "experience": [
                    {"role": "Backend Developer", "company": "TechCorp", "period": "2023 - Presente", "description": [
                        "Desarrollé 8 APIs REST en Django que procesaron +100K peticiones diarias",
                        "Implementé pipeline CI/CD con GitHub Actions reduciendo tiempos de despliegue un 60%",
                        "Migré base de datos de MySQL a PostgreSQL mejorando tiempos de consulta un 35%"
                    ]}
                ],
                "education": [{"degree": "CFGS Desarrollo de Aplicaciones Multiplataforma", "institution": "IES Tecnológico", "year": "2022"}],
                "skills": {"Backend": ["Python", "Django", "Java"], "Bases de datos": ["PostgreSQL", "MySQL"], "Cloud": ["AWS", "Docker"], "CI/CD": ["GitHub Actions"]},
                "projects": [{"name": "Job Scraper AI", "description": "Sistema de scraping con IA que analiza ofertas de 9 plataformas, genera CVs personalizados y sincroniza con Notion. Procesa +500 ofertas diarias."}],
            }

        feedback_block = ""
        if feedback:
            feedback_block = f"""
        FEEDBACK DEL USUARIO SOBRE EL CV ANTERIOR:
        El usuario quiere lo siguiente para mejorar el CV:
        {feedback}
        Incorpora esta feedback en el nuevo CV. Si el usuario pide más detalle en alguna experiencia, añade más bullet points con métricas. Si pide cambiar el tono, adáptalo. Si pide quitar algo, elimínalo."""

        lang_name = "español" if language == "es" else "English"
        section_names = {
            "es": {"summary": "PERFIL PROFESIONAL", "experience": "EXPERIENCIA LABORAL", "education": "FORMACIÓN", "skills": "HABILIDADES", "projects": "PROYECTOS RELEVANTES"},
            "en": {"summary": "PROFESSIONAL SUMMARY", "experience": "WORK EXPERIENCE", "education": "EDUCATION", "skills": "SKILLS", "projects": "PROJECTS"},
        }[language]

        prompt = f"""
        Eres un experto en creación de CVs técnicos profesionales. Genera un CV de alta calidad optimizado para ESTA oferta de empleo. Responde en {lang_name}.

        REGLAS OBLIGATORIAS (las 10 reglas de un CV técnico profesional):

        1. LEGIBILIDAD EN 30-60 SEGUNDOS: El CV debe ser scaneable rápidamente. Títulos claros, buen espacio en blanco, información ordenada cronológicamente (lo más reciente primero).

        2. PERFIL TÉCNICO CLARO desde el primer párrafo: cargo objetivo + años de experiencia + especialización + tecnologías principales.
        Ejemplo: "Backend Software Engineer con 4 años de experiencia desarrollando APIs REST escalables con Java, Spring Boot y PostgreSQL."

        3. HABILIDADES AGRUPADAS POR CATEGORÍA (nunca lista plana):
        ✅ Backend: Java, Spring Boot, Hibernate
           Bases de datos: PostgreSQL, MySQL
           Cloud: AWS, Docker, Kubernetes
           CI/CD: GitHub Actions, Jenkins
        ❌ Java, Spring, AWS, Docker, Python, Node, React, Angular, Mongo, Redis...

        4. LOGROS CUANTIFICADOS en cada experiencia (OBLIGATORIO):
        ✅ "Desarrollé 12 APIs REST en Spring Boot que redujeron tiempos de respuesta en un 40%"
        ✅ "Migré aplicación monolítica a microservicios, reduciendo tiempo de despliegue de 2 horas a 15 minutos"
        ✅ "Procesé 2 millones de eventos diarios con Kafka"
        ❌ "Desarrollé APIs"
        ❌ "Mantenimiento de aplicaciones"

        5. MÉTRICAS SIEMPRE QUE SEA POSIBLE: %, tiempo, usuarios, volumen, rendimiento, ahorro.
        Ejemplos: reduje consumo un 30%, soporté 500K usuarios, automatizé pipeline de 3h a 20min.

        6. CONOCIMIENTOS TÉCNICOS PROFUNDOS:
        ✅ "Diseñé arquitectura hexagonal con Spring Boot utilizando CQRS, Kafka y PostgreSQL"
        ❌ "Java + Spring"

        7. PROYECTOS RELEVANTES (no básicos):
        ✅ Aplicaciones completas, open source, SaaS, herramientas propias
        ❌ To-Do List, Calculadora, CRUD sencillo

        8. ADAPTADO A LA OFERTA: Las tecnologías que pide la oferta deben aparecer destacadas si realmente se dominan.

        9. ATS-COMPATIBLE: Texto plano, sin tablas complejas, sin iconos, títulos estándar ({section_names['experience']}, {section_names['skills']}, {section_names['education']}), incluir keywords de la oferta.

        10. EVOLUCIÓN PROFESIONAL: Mostrar progresión (Junior → Backend → Senior) o mayor complejidad técnica (CRUD → Microservicios → Cloud).

        CV ORIGINAL DEL CANDIDATO:
        ---
        {cv_text}
        ---

        CONSEJOS DEL ANALISTA PARA ESTA OFERTA:
        {advice}

        TECNOLOGÍAS REQUERIDAS POR LA OFERTA:
        {tech_stack}

        Oferta:
        Puesto: {offer_title}
        Empresa: {company}
        {feedback_block}

        Responde CON SOLO el JSON con esta estructura exacta:
        {{
            "name": "Nombre completo del candidato",
            "contact": "email | teléfono | ubicación",
            "summary": "Resumen profesional de 3-4 líneas con cargo objetivo + años + especialización + tech principal",
            "experience": [
                {{
                    "role": "Título del puesto",
                    "company": "Empresa",
                    "period": "2023 - Presente",
                    "description": ["Bullet point 1 con métrica cuantificada", "Bullet point 2 con resultado medible"]
                }}
            ],
            "education": [
                {{"degree": "Título", "institution": "Centro", "year": "2023"}}
            ],
            "skills": {{
                "Backend": ["Java", "Spring Boot"],
                "Bases de datos": ["PostgreSQL"],
                "Cloud": ["AWS", "Docker"]
            }},
            "projects": [
                {{"name": "Nombre del proyecto", "description": "Descripción de 1-2 líneas con impacto/tecnologías"}}
            ]
        }}
        """

        import time
        from google.api_core.exceptions import ResourceExhausted

        for attempt in range(2):
            try:
                generation_config = genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                data = json.loads(response.text)
                return data
            except ResourceExhausted:
                if attempt < 1:
                    if self._on_429():
                        print(f"\n[Gemini] 429 → cv_content. Key #{self.key_pool.active_index + 1}. Esperando 5s...")
                        time.sleep(5)
                    else:
                        raise RuntimeError("429 - Todas las API keys agotadas en cv_content.")
                else:
                    raise RuntimeError("429 - Todas las API keys agotadas en cv_content.")
            except Exception as e:
                raise e
        raise RuntimeError("429 - Todas las API keys agotadas en cv_content.")

    def generate_interview_prep(self, cv_text: str, offer_title: str, company: str, tech_stack: str, offer_description: str, language: str = "es") -> InterviewPrep:
        """
        Genera una guía de preparación para entrevista basada en la oferta y el CV.
        Retorna un InterviewPrep con preguntas técnicas, comportamentales, temas clave y consejos.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            lang_name = "español" if language == "es" else "English"
            if language == "es":
                return InterviewPrep(
                    technical_questions=[
                        {"question": "¿Cómo diseñas una API REST escalable?", "answer": "Sigo principios de arquitectura hexagonal, uso caché Redis y balanceo de carga con Nginx."},
                        {"question": "Explica la diferencia entre SQL y NoSQL", "answer": "SQL es relacional y consistente, NoSQL es flexible y escalable horizontalmente."},
                    ],
                    behavioral_questions=[
                        {"question": "Describe una situación donde tuviste que resolver un problema complejo", "answer": "Migré un monolito a microservicios, reduciendo tiempos de despliegue de 2h a 15min."},
                    ],
                    key_topics=[tech.strip() for tech in tech_stack.split(",")[:5]],
                    preparation_tips=["Revisa la documentación oficial de las tecnologías requeridas", "Prepara ejemplos concretos de tu experiencia"],
                )
            else:
                return InterviewPrep(
                    technical_questions=[
                        {"question": "How do you design a scalable REST API?", "answer": "I follow hexagonal architecture principles, use Redis caching and Nginx load balancing."},
                        {"question": "Explain the difference between SQL and NoSQL", "answer": "SQL is relational and consistent, NoSQL is flexible and horizontally scalable."},
                    ],
                    behavioral_questions=[
                        {"question": "Describe a situation where you had to solve a complex problem", "answer": "I migrated a monolith to microservices, reducing deployment times from 2h to 15min."},
                    ],
                    key_topics=[tech.strip() for tech in tech_stack.split(",")[:5]],
                    preparation_tips=["Review official documentation of required technologies", "Prepare concrete examples from your experience"],
                )

        lang_name = "español" if language == "es" else "English"

        prompt = f"""
        Eres un reclutador técnico experto. Genera una guía de preparación para una entrevista para este puesto.
        Responde en {lang_name}.

        Puesto: {offer_title}
        Empresa: {company}
        Tecnologías requeridas: {tech_stack}
        Descripción de la oferta:
        {offer_description}

        CV del candidato:
        ---
        {cv_text}
        ---

        Genera:
        1. 5-8 preguntas técnicas probables que podrían hacerse en esta entrevista, con respuestas sugeridas basadas en el CV
        2. 3-5 preguntas comportamentales (STAR method) con respuestas sugeridas
        3. 3-5 temas clave que el candidato debe repasar
        4. 3-5 consejos específicos para esta oferta concreta

        Responde CON SOLO el JSON con esta estructura exacta:
        {{
            "technical_questions": [{{"question": "Pregunta técnica", "answer": "Respuesta sugerida"}}],
            "behavioral_questions": [{{"question": "Pregunta comportamental", "answer": "Respuesta sugerida"}}],
            "key_topics": ["Tema 1", "Tema 2"],
            "preparation_tips": ["Consejo 1", "Consejo 2"]
        }}
        """

        import time
        from google.api_core.exceptions import ResourceExhausted

        for attempt in range(2):
            try:
                generation_config = genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=InterviewPrep,
                    temperature=0.2
                )
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                data = json.loads(response.text)
                return InterviewPrep(**data)
            except ResourceExhausted:
                if attempt < 1:
                    if self._on_429():
                        print(f"\n[Gemini] 429 → interview_prep. Key #{self.key_pool.active_index + 1}. Esperando 5s...")
                        time.sleep(5)
                    else:
                        raise RuntimeError("429 - Todas las API keys agotadas en interview_prep.")
                else:
                    raise RuntimeError("429 - Todas las API keys agotadas en interview_prep.")
            except Exception as e:
                raise e
        raise RuntimeError("429 - Todas las API keys agotadas en interview_prep.")

    def generate_market_report(self, cv_text: str, jobs_data: list) -> str:
        """
        Genera un informe de mercado semanal en HTML basado en las ofertas recientes.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return """<h2>📊 Informe de Mercado Semanal</h2>
<p><strong>Período:</strong> Últimos 7 días</p>
<p><strong>Ofertas analizadas:</strong> {}</p>
<h3>🏆 Tech Stack Más Demandado</h3>
<ol>
<li><strong>Python</strong> — 18 ofertas (72%)</li>
<li><strong>Docker</strong> — 14 ofertas (56%)</li>
<li><strong>AWS</strong> — 12 ofertas (48%)</li>
<li><strong>React</strong> — 10 ofertas (40%)</li>
<li><strong>Kubernetes</strong> — 8 ofertas (32%)</li>
</ol>
<h3>💰 Rangos Salariales</h3>
<ul>
<li><strong>Junior (0-2 años):</strong> 24.000€ - 30.000€</li>
<li><strong>Mid (3-5 años):</strong> 32.000€ - 42.000€</li>
<li><strong>Senior (5+ años):</strong> 45.000€ - 60.000€</li>
</ul>
<h3>🏢 Empresas Que Más Contratan</h3>
<ul><li>InfoJobs Performance — 5 ofertas</li><li>RemoteOK — 4 ofertas</li><li>GetOnBoard — 8 ofertas</li></ul>
<h3>📈 Tendencias</h3>
<ul>
<li>El trabajo remoto sigue en alza: 68% de ofertas son 100% remotas</li>
<li>La demanda de DevOps/SRE crece un 25% vs mes anterior</li>
<li>Python supera a Java como lenguaje más demandado</li>
</ul>""".format(len(jobs_data))

        # Preparar datos para el informe
        all_techs = {}
        companies = {}
        remote_count = 0
        salaries = []

        for job in jobs_data:
            # Tech stack
            for tech in job.get("tech_stack", []):
                all_techs[tech] = all_techs.get(tech, 0) + 1
            # Companies
            company = job.get("company", "N/A")
            companies[company] = companies.get(company, 0) + 1
            # Remote
            if job.get("work_mode") == "Remoto":
                remote_count += 1
            # Salary
            salary = job.get("salary")
            if salary:
                try:
                    salaries.append(int(str(salary).replace(".", "").replace(",", "")))
                except (ValueError, TypeError):
                    pass

        top_techs = sorted(all_techs.items(), key=lambda x: x[1], reverse=True)[:10]
        top_companies = sorted(companies.items(), key=lambda x: x[1], reverse=True)[:5]
        remote_pct = (remote_count / len(jobs_data) * 100) if jobs_data else 0

        avg_salary = sum(salaries) // len(salaries) if salaries else 0
        min_salary = min(salaries) if salaries else 0
        max_salary = max(salaries) if salaries else 0

        tech_rows = "".join(
            f"<li><strong>{tech}</strong> — {count} ofertas ({count/len(jobs_data)*100:.0f}%)</li>"
            for tech, count in top_techs
        )
        company_rows = "".join(
            f"<li><strong>{company}</strong> — {count} ofertas</li>"
            for company, count in top_companies
        )

        prompt = f"""
        Genera un informe de mercado laboral tech en HTML basado en estos datos.
        El informe debe ser visual, con emojis, y fácil de leer.
        Incluye: tech stack más demandado, rangos salariales, empresas que más contratan, tendencias.
        Datos:
        - Total ofertas: {len(jobs_data)}
        - Tech más demandado: {top_techs}
        - Empresas top: {top_companies}
        - % remoto: {remote_pct:.0f}%
        - Salario promedio: {avg_salary}€, rango: {min_salary}€ - {max_salary}€
        - CV skills: {', '.join(job.get('tech_stack', [])[:5] for job in jobs_data[:1])}

        Responde SOLO con el HTML del informe, sin explicaciones.
        """

        import time
        from google.api_core.exceptions import ResourceExhausted

        for attempt in range(2):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except ResourceExhausted:
                if attempt < 1:
                    if self._on_429():
                        print(f"\n[Gemini] 429 → market_report. Key #{self.key_pool.active_index + 1}. Esperando 5s...")
                        time.sleep(5)
                    else:
                        raise RuntimeError("429 - Todas las API keys agotadas en market_report.")
                else:
                    raise RuntimeError("429 - Todas las API keys agotadas en market_report.")
            except Exception as e:
                raise e
        raise RuntimeError("429 - Todas las API keys agotadas en market_report.")

    def research_company(self, company_name: str, offer_title: str, offer_description: str, language: str = "es") -> CompanyProfile:
        """
        Investiga una empresa basándose en la oferta de empleo y conocimiento general.
        Devuelve un perfil de empresa con pros, contros, cultura, etc.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return CompanyProfile(
                name=company_name,
                industry="Tecnología / Software",
                size="mediana",
                tech_stack=["Python", "JavaScript", "Cloud"],
                culture="Agile, orientada a resultados",
                pros=["Buena reputación", "Tecnologías modernas"],
                cons=["Puede exigir disponibilidad alta"],
                salary_range="25.000€ - 40.000€",
                remote_friendly=True,
                recommendation="Empresa interesante para crecer técnicamente."
            )

        lang_name = "español" if language == "es" else "English"

        prompt = f"""
        Eres un analista de empresas tech. Investiga la empresa "{company_name}" basándote en la siguiente oferta de empleo y tu conocimiento general.

        Proporciona un perfil completo de la empresa en {lang_name}:
        - Sector/industria
        - Tamaño aproximado (startup/mediana/grande/enterprise)
        - Tecnologías principales que usa
        - Cultura laboral estimada
        - Pros de trabajar ahí (3-5 puntos)
        - Cons o cosas a tener en cuenta (2-3 puntos)
        - Rango salarial aproximado para este tipo de puesto
        - Si es remote-friendly
        - Breve recomendación personalizada

        Oferta de empleo:
        Puesto: {offer_title}
        Empresa: {company_name}
        Descripción:
        {offer_description[:2000]}
        """

        response_text = self._generate_with_retry(prompt, CompanyProfile)
        data = json.loads(response_text)
        return CompanyProfile(**data)

    def match_projects(self, cv_text: str, offer_title: str, offer_description: str, user_projects: str = "", language: str = "es") -> ProjectMatch:
        """
        Analiza cómo encajan los proyectos personales del candidato con la oferta.
        """
        import os
        if os.getenv("MOCK_GEMINI") == "true":
            return ProjectMatch(
                project_relevance=60,
                matching_projects=["Proyecto con IA"],
                missing_project_types=["Proyecto con cloud"],
                project_advice="Crea un proyecto que combine las tecnologías de la oferta."
            )

        lang_name = "español" if language == "es" else "English"
        projects_text = user_projects if user_projects else "No se han proporcionado proyectos personales específicos."

        prompt = f"""
        Eres un experto en desarrollo de software y evaluación de portafolios.
        Analiza los proyectos personales del candidato y evalúa cuánto encajan con la oferta de empleo.

        Proyectos personales del candidato:
        ---
        {projects_text}
        ---

        CV del candidato:
        ---
        {cv_text[:3000]}
        ---

        Oferta de empleo:
        Puesto: {offer_title}
        Descripción:
        {offer_description[:2000]}

        Responde en {lang_name}.
        """

        response_text = self._generate_with_retry(prompt, ProjectMatch)
        data = json.loads(response_text)
        return ProjectMatch(**data)
