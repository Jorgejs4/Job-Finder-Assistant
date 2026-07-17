import json
import google.generativeai as genai
from pydantic import BaseModel, Field
from typing import List, Optional
import config

# Configurar el SDK de Gemini
if config.GEMINI_API_KEY:
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

class OfferMatch(BaseModel):
    match_score: int = Field(
        description="Puntuación de coincidencia del 0 al 100 de qué tan bien encaja el CV en la oferta. Sé riguroso y objetivo, puntuando bajo si el rol no coincide en absoluto."
    )
    tech_stack: List[str] = Field(
        description="Lista de tecnologías y herramientas requeridas por la oferta (ej: ['Docker', 'AWS', 'FastAPI']). Extrae las tecnologías reales mencionadas en la oferta, no pongas siempre las mismas."
    )
    tailored_advice: str = Field(
        description="Consejos concretos en español para modificar o adaptar el CV para esta oferta específica de forma personalizada (ej: 'Resalta tu experiencia con Java en tu rol anterior y menciona tu proyecto de Vercel'). Debe ser personalizado según el puesto."
    )
    estimated_salary: int = Field(
        description="Salario estimado anual bruto en euros (EUR) para esta oferta. Si la oferta indica el salario o rango (ej: '30.000€ - 35.000€' o '2.500€/mes'), calcula el salario anual bruto correspondiente como un entero (ej: 32000). Si la oferta NO especifica ningún salario, la IA debe estimar un salario anual bruto de mercado realista para este puesto en España considerando el rol, las tecnologías requeridas, la modalidad y la experiencia solicitada, y devolverlo como un entero (ej: 28000). No devuelvas null ni 0."
    )
    work_mode: str = Field(
        description="Modalidad de trabajo detectada en la oferta. Debe ser exactamente uno de estos valores: 'Presencial', 'Remoto', 'Híbrido'."
    )
    salary_is_estimate: bool = Field(
        description="True si el salario fue estimado por la IA porque la oferta original no mencionaba ningún salario ni rango salarial. False si la oferta original sí especificaba explícitamente un salario o rango."
    )
    required_experience: int = Field(
        description="Número de años de experiencia laboral que pide la empresa para el puesto. Si la oferta menciona explícitamente los años (ej: '3 años de experiencia'), devuelve ese número. Si solo pone 'junior' o no menciona experiencia, devuelve 0. Si pone 'senior' sin número concreto, devuelve 5. Máximo 20."
    )
    cover_letter: str = Field(
        description="Carta de presentación personalizada en español, 150-250 palabras, 3-4 párrafos. Tono profesional pero cercano, mencionando tecnologías específicas del candidato relevantes para ESTA oferta."
    )
    cv_summary: str = Field(
        description="Resumen profesional de 3-4 líneas optimizado para este puesto específico."
    )
    cv_experience_adapted: List[dict] = Field(
        description="Experiencia laboral reordenada y adaptada. Cada item: {role: str, company: str, period: str, description: str (2-3 líneas con logros y tech relevantes)}"
    )
    cv_skills: List[str] = Field(
        description="Solo las habilidades más relevantes para este puesto, ordenadas por relevancia."
    )
    cv_projects: List[dict] = Field(
        description="Proyectos relevantes reformulados para encajar con el puesto. Cada item: {name: str, description: str (1-2 líneas)}"
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

class GeminiClient:
    def __init__(self):
        # Permite configurar el modelo desde las variables de entorno (ej. para cambiar a gemini-1.5-flash-latest, etc.)
        import os
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self.model = genai.GenerativeModel(self.model_name)

    def _generate_with_retry(self, prompt: str, schema) -> str:
        """
        Realiza la llamada a la API de Gemini con reintentos automáticos y
        retroceso exponencial si se excede la cuota (error 429 / ResourceExhausted).
        """
        import time
        from google.api_core.exceptions import ResourceExhausted
        
        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2
        )
        
        for attempt in range(5):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                return response.text
            except ResourceExhausted:
                wait_time = (2 ** attempt) * 3 + 2  # 5s, 8s, 14s, 26s, 50s
                print(f"\n[Gemini] Límite de cuota (429) excedido. Esperando {wait_time}s para reintentar (intento {attempt+1}/5)...")
                time.sleep(wait_time)
            except Exception as e:
                raise e
                
        raise RuntimeError("No se pudo conectar con la API de Gemini tras 5 intentos debido a la cuota (429).")

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

    def match_offer(self, cv_text: str, offer_title: str, offer_description: str, experience_hint: int = 0) -> OfferMatch:
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
                
            print(f"  - [Smart Mock] Match: {match_score}%, Stack: {tech_stack}, Mod: {work_mode}, Sal: {estimated_salary}€")
            return OfferMatch(
                match_score=match_score,
                tech_stack=tech_stack,
                tailored_advice=tailored_advice,
                estimated_salary=estimated_salary,
                work_mode=work_mode,
                salary_is_estimate=len(re.findall(r'(\d{2})[\s.]?(\d{3})', offer_description)) == 0,
                required_experience=experience_hint,
                cover_letter=f"Estimado equipo de reclutamiento,\n\nMe dirijo a ustedes para presentar mi candidatura a la posición de {offer_title}. Con mi formación en desarrollo de software y mi experiencia práctica, estoy preparado para contribuir a su equipo.\n\nMi perfil combina conocimientos técnicos sólidos con una mentalidad de aprendizaje continuo.\n\nQuedo a su disposición para ampliar cualquier información.\n\nUn cordial saludo.",
                cv_summary="Desarrollador de software junior con formación en desarrollo de aplicaciones multiplataforma y experiencia en proyectos de IA.",
                cv_experience_adapted=[],
                cv_skills=tech_stack[:5],
                cv_projects=[],
            )

        prompt = f"""
        Eres un reclutador experto y especialista en optimización de CVs. 
        Compara el siguiente currículum con la oferta de empleo provista y genera TODO lo siguiente en una sola respuesta:

        1. MATCH SCORE: Calcula una puntuación de compatibilidad (0 a 100). Si la oferta es para un puesto manual o no relacionado con el perfil de desarrollo del candidato (como operario de cementerio, reponedor, personal de limpieza, etc.), el Match Score DEBE ser muy bajo (por debajo de 10).
        2. TECH STACK: Identifica las tecnologías y herramientas requeridas en la oferta a partir del texto. Extrae tecnologías reales.
        3. TAILORED_ADVICE: Escribe consejos breves, personalizados y accionables para adaptar el CV a ESTA oferta específica.
        4. ESTIMATED_SALARY: Calcula el salario anual bruto estimado en euros. Si el texto no lo menciona, estima un salario realista para este puesto en España.
        5. WORK_MODE: Modalidad de trabajo exacta: 'Presencial', 'Remoto' o 'Híbrido'.
        6. REQUIRED_EXPERIENCE: Años de experiencia requeridos (0=junior, 3=mid, 5=senior sin número).
        7. COVER_LETTER: Genera una carta de presentación personalizada en español (150-250 palabras, 3-4 párrafos). Sé específico: menciona tecnologías concretas del CV relevantes para ESTA oferta. Tono profesional pero cercano. No uses frases genéricas como "Me dirijo a ustedes".
        8. CV SUMMARY: Resumen profesional de 3-4 líneas optimizado para ESTE puesto.
        9. CV_EXPERIENCE_ADAPTED: Reorganiza la experiencia laboral adaptando las descripciones para resaltar lo más relevante para ESTA oferta.
        10. CV_SKILLS: Solo las habilidades más relevantes para este puesto ordenadas por relevancia.
        11. CV_PROJECTS: Proyectos reformulados para encajar mejor con el puesto.

        Currículum del candidato:
        ---
        {cv_text}
        ---

        Oferta de Empleo:
        Puesto: {offer_title}
        Descripción:
        {offer_description}
        """

        response_text = self._generate_with_retry(prompt, OfferMatch)
        
        data = json.loads(response_text)
        return OfferMatch(**data)

    def generate_cover_letter(self, cv_text: str, offer_title: str, company: str, offer_description: str) -> str:
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

        prompt = f"""
        Eres un experto en redacción de cartas de presentación profesionales.
        Genera una carta de presentación personalizada en español para esta oferta de empleo.

        REGLAS:
        - La carta debe tener 3-4 párrafos cortos (máximo 4 oraciones cada uno)
        - Sé específico: menciona tecnologías y experiencias concretas del CV relevantes para ESTA oferta
        - Tono profesional pero cercano, sin ser genérico
        - No uses frases hechas como "Me dirijo a ustedes para..." o "Quedo a su disposición"
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

        for attempt in range(5):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except ResourceExhausted:
                wait_time = (2 ** attempt) * 3 + 2
                print(f"\n[Gemini] Cuota excedida en cover_letter. Esperando {wait_time}s (intento {attempt+1}/5)...")
                time.sleep(wait_time)
            except Exception as e:
                raise e
        raise RuntimeError("No se pudo generar cover_letter tras 5 intentos.")

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

    def generate_cv_content(self, cv_text: str, offer_title: str, company: str, advice: str, tech_stack: str, feedback: str = None) -> dict:
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

        prompt = f"""
        Eres un experto en creación de CVs técnicos profesionales. Genera un CV de alta calidad optimizado para ESTA oferta de empleo.

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

        9. ATS-COMPATIBLE: Texto plano, sin tablas complejas, sin iconos, títulos estándar (Experiencia, Habilidades, Formación), incluir keywords de la oferta.

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

        for attempt in range(5):
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
                wait_time = (2 ** attempt) * 3 + 2
                print(f"\n[Gemini] Cuota excedida en cv_content. Esperando {wait_time}s (intento {attempt+1}/5)...")
                time.sleep(wait_time)
            except Exception as e:
                raise e
        raise RuntimeError("No se pudo generar cv_content tras 5 intentos.")

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

        for attempt in range(5):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except ResourceExhausted:
                wait_time = (2 ** attempt) * 3 + 2
                print(f"\n[Gemini] Cuota excedida en market_report. Esperando {wait_time}s (intento {attempt+1}/5)...")
                time.sleep(wait_time)
            except Exception as e:
                raise e
        raise RuntimeError("No se pudo generar market_report tras 5 intentos.")
